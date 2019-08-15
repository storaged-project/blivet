#
# iscsi.py - iscsi class
#
# Copyright (C) 2005, 2006  IBM, Inc.  All rights reserved.
# Copyright (C) 2006  Red Hat, Inc.  All rights reserved.
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#

from . import udev
from . import util
from .flags import flags
from .i18n import _
from .storage_log import log_exception_info
from . import safe_dbus
import os
import re
import shutil
import time
import itertools
from collections import namedtuple
from distutils.spawn import find_executable

import gi
gi.require_version("GLib", "2.0")
from gi.repository import GLib

import logging
log = logging.getLogger("blivet")

# Note that stage2 copies all files under /sbin to /usr/sbin
ISCSID = ""
INITIATOR_FILE = "/etc/iscsi/initiatorname.iscsi"

ISCSI_MODULES = ['cxgb3i', 'bnx2i', 'be2iscsi']


STORAGED_SERVICE = "org.freedesktop.UDisks2"
STORAGED_PATH = "/org/freedesktop/UDisks2"
STORAGED_MANAGER_PATH = "/org/freedesktop/UDisks2/Manager"
MANAGER_IFACE = "org.freedesktop.UDisks2.Manager"
INITIATOR_IFACE = MANAGER_IFACE + ".ISCSI.Initiator"
SESSION_IFACE = STORAGED_SERVICE + ".ISCSI.Session"


def has_iscsi():
    global ISCSID

    if not os.access("/sys/module/iscsi_tcp", os.X_OK):
        return False

    if not ISCSID:
        location = find_executable("iscsid")
        if not location:
            return False
        ISCSID = location
        log.info("ISCSID is %s", ISCSID)

    return True


TargetInfo = namedtuple("TargetInfo", ["ipaddr", "port"])


class NodeInfo(object):
    """Simple representation of node information."""
    def __init__(self, name, tpgt, address, port, iface):
        self.name = name
        self.tpgt = tpgt
        self.address = address
        self.port = port
        self.iface = iface
        # These get set by log_into_node, but *NOT* _login
        self.username = None
        self.password = None
        self.r_username = None
        self.r_password = None

    @property
    def conn_info(self):
        """The 5-tuple of connection info (no auth info). This form
        is useful for interacting with storaged.
        """
        return (self.name, self.tpgt, self.address, self.port, self.iface)


class LoginInfo(object):
    def __init__(self, node, logged_in):
        self.node = node
        self.logged_in = logged_in


def _to_node_infos(variant):
    """Transforms an 'a(sisis)' GLib.Variant into a list of NodeInfo objects"""
    return [NodeInfo(*info) for info in variant]


class iSCSIDependencyGuard(util.DependencyGuard):
    error_msg = "storaged iSCSI functionality not available"

    def _check_avail(self):
        try:
            if not safe_dbus.check_object_available(STORAGED_SERVICE, STORAGED_MANAGER_PATH, MANAGER_IFACE):
                return False
            # storaged is modular and we need to make sure it has the iSCSI module
            # loaded (this also autostarts storaged if it isn't running already)
            safe_dbus.call_sync(STORAGED_SERVICE, STORAGED_MANAGER_PATH, MANAGER_IFACE,
                                "EnableModules", GLib.Variant("(b)", (True,)))
        except safe_dbus.DBusCallError:
            return False
        return safe_dbus.check_object_available(STORAGED_SERVICE, STORAGED_MANAGER_PATH, INITIATOR_IFACE)


storaged_iscsi_required = iSCSIDependencyGuard()


class iSCSI(object):
    """ iSCSI utility class.

        This class will automatically discover and login to iBFT (or
        other firmware) configured iscsi devices when the startup() method
        gets called. It can also be used to manually configure iscsi devices
        through the add_target() method.

        As this class needs to make sure certain things like starting iscsid
        and logging in to firmware discovered disks only happens once
        and as it keeps a global list of all iSCSI devices it is implemented as
        a Singleton.

        .. warning::
            Since this is a singleton class, calling deepcopy() on the instance
            just returns ``self`` with no copy being created.
    """

    def __init__(self):
        # Dictionary mapping discovered TargetInfo data to lists of LoginInfo
        # data.
        self.discovered_targets = {}
        # This list contains nodes discovered through iBFT (or other firmware)
        self.ibft_nodes = []
        self._initiator = ""
        self.started = False
        self.ifaces = {}

        self.__connection = None

        if flags.ibft:
            try:
                initiatorname = self._call_initiator_method("GetFirmwareInitiatorName")[0]
                self._initiator = initiatorname
            except Exception:  # pylint: disable=broad-except
                log_exception_info(fmt_str="failed to get initiator name from iscsi firmware")

    # So that users can write iscsi() to get the singleton instance
    def __call__(self):
        return self

    def __deepcopy__(self, memo_dict):
        # pylint: disable=unused-argument
        return self

    @property
    @storaged_iscsi_required(critical=False, eval_mode=util.EvalMode.onetime)
    def available(self):
        return True

    @property
    def _connection(self):
        if not self.__connection:
            self.__connection = safe_dbus.get_new_system_connection()

        return self.__connection

    @storaged_iscsi_required(critical=True, eval_mode=util.EvalMode.onetime)
    def _call_initiator_method(self, method, args=None):
        """Class a method of the ISCSI.Initiator DBus object

        :param str method: name of the method to call
        :param params: arguments to pass to the method
        :type params: GLib.Variant

        """
        return safe_dbus.call_sync(STORAGED_SERVICE, STORAGED_MANAGER_PATH,
                                   INITIATOR_IFACE, method, args,
                                   connection=self._connection)

    @property
    def initiator_set(self):
        """True if initiator is set at our level."""
        return self._initiator != ""

    @property
    @storaged_iscsi_required(critical=False, eval_mode=util.EvalMode.onetime)
    def initiator(self):
        if self._initiator != "":
            return self._initiator

        # udisks returns initiatorname as a NULL terminated bytearray
        raw_initiator = bytes(self._call_initiator_method("GetInitiatorNameRaw")[0][:-1])
        return raw_initiator.decode("utf-8", errors="replace")

    @initiator.setter
    @storaged_iscsi_required(critical=True, eval_mode=util.EvalMode.onetime)
    def initiator(self, val):
        if self.initiator_set and val != self._initiator:
            raise ValueError(_("Unable to change iSCSI initiator name once set"))
        if len(val) == 0:
            raise ValueError(_("Must provide an iSCSI initiator name"))

        log.info("Setting up iSCSI initiator name %s", self.initiator)
        args = GLib.Variant("(sa{sv})", (val, None))
        self._call_initiator_method("SetInitiatorName", args)
        self._initiator = val

    def active_nodes(self, target=None):
        """Nodes logged in to"""
        if target:
            return [info.node for info in self.discovered_targets.get(target, [])
                    if info.logged_in]
        else:
            return [info.node for info in itertools.chain(*list(self.discovered_targets.values()))
                    if info.logged_in] + self.ibft_nodes

    @property
    def mode(self):
        if not self.active_nodes():
            return "none"
        if self.ifaces:
            return "bind"
        else:
            return "default"

    def _mark_node_active(self, node, active=True):
        """Mark node as one logged in to

           Returns False if not found
        """
        for login_infos in self.discovered_targets.values():
            for info in login_infos:
                if info.node is node:
                    info.logged_in = active
                    return True
        return False

    def _login(self, node_info, extra=None):
        """Try to login to the iSCSI node

        :type node_info: :class:`NodeInfo`
        :param dict extra: extra configuration for the node (e.g. authentication info)
        :raises :class:`~.safe_dbus.DBusCallError`: if login fails

        """

        if extra is None:
            extra = dict()
        extra["node.startup"] = GLib.Variant("s", "automatic")

        args = GLib.Variant("(sisisa{sv})", node_info.conn_info + (extra,))
        self._call_initiator_method("Login", args)

    @storaged_iscsi_required(critical=False, eval_mode=util.EvalMode.onetime)
    def _get_active_sessions(self):
        try:
            objects = safe_dbus.call_sync(STORAGED_SERVICE,
                                          STORAGED_PATH,
                                          'org.freedesktop.DBus.ObjectManager',
                                          'GetManagedObjects',
                                          None)[0]
        except safe_dbus.DBusCallError:
            log_exception_info(log.info, "iscsi: Failed to get active sessions.")
            return []

        sessions = (obj for obj in objects.keys() if re.match(r'.*/iscsi/session[0-9]+$', obj))

        active = []
        for session in sessions:
            properties = objects[session][SESSION_IFACE]
            active.append(NodeInfo(properties["target_name"],
                                   properties["tpgt"],
                                   properties["persistent_address"],
                                   properties["persistent_port"],
                                   None))

        return active

    @storaged_iscsi_required(critical=False, eval_mode=util.EvalMode.onetime)
    def _start_ibft(self):
        if not flags.ibft:
            return

        args = GLib.Variant("(a{sv})", ([], ))
        try:
            found_nodes, _n_nodes = self._call_initiator_method("DiscoverFirmware", args)
        except safe_dbus.DBusCallError:
            log_exception_info(log.info, "iscsi: No IBFT info found.")
            # an exception here means there is no ibft firmware, just return
            return

        found_nodes = _to_node_infos(found_nodes)
        active_nodes = self._get_active_sessions()
        for node in found_nodes:
            if any(node.name == a.name and node.tpgt == a.tpgt and
                   node.address == a.address and node.port == a.port for a in active_nodes):
                log.info("iscsi IBFT: already logged in node %s at %s:%s through %s",
                         node.name, node.address, node.port, node.iface)
                self.ibft_nodes.append(node)
            try:
                self._login(node)
                log.info("iscsi IBFT: logged into %s at %s:%s through %s",
                         node.name, node.address, node.port, node.iface)
                self.ibft_nodes.append(node)
            except safe_dbus.DBusCallError as e:
                log.error("Could not log into ibft iscsi target %s: %s",
                          node.name, str(e))

        self.stabilize()

    def stabilize(self):
        # Wait for udev to create the devices for the just added disks

        # It is possible when we get here the events for the new devices
        # are not send yet, so sleep to make sure the events are fired
        time.sleep(2)
        udev.settle()

    def create_interfaces(self, ifaces):
        for iface in ifaces:
            iscsi_iface_name = "iface%d" % len(self.ifaces)
            # iscsiadm -m iface -I iface0 --op=new
            util.run_program(["iscsiadm", "-m", "iface",
                              "-I", iscsi_iface_name, "--op=new"])
            # iscsiadm -m iface -I iface0 --op=update -n iface.net_ifacename -v eth0
            util.run_program(["iscsiadm", "-m", "iface",
                              "-I", iscsi_iface_name, "--op=update",
                              "-n", "iface.net_ifacename", "-v", iface])

            self.ifaces[iscsi_iface_name] = iface
            log.debug("created_interface %s:%s", iscsi_iface_name, iface)

    def delete_interfaces(self):
        if not self.ifaces:
            return None
        for iscsi_iface_name in self.ifaces:
            # iscsiadm -m iface -I iface0 --op=delete
            util.run_program(["iscsiadm", "-m", "iface",
                              "-I", iscsi_iface_name, "--op=delete"])
        self.ifaces = {}

    def startup(self):
        if self.started:
            return

        if not has_iscsi():
            return

        if self._initiator == "":
            log.info("no initiator set")
            return

        for fulldir in (os.path.join("/var/lib/iscsi", d) for d in
                        ['ifaces', 'isns', 'nodes', 'send_targets', 'slp', 'static']):
            if not os.path.isdir(fulldir):
                os.makedirs(fulldir, 0o755)

        log.info("iSCSI startup")
        util.run_program(['modprobe', '-a'] + ISCSI_MODULES)
        # iscsiuio is needed by Broadcom offload cards (bnx2i). Currently
        # not present in iscsi-initiator-utils for Fedora.
        iscsiuio = find_executable('iscsiuio')
        if iscsiuio:
            log.debug("iscsi: iscsiuio is at %s", iscsiuio)
            util.run_program([iscsiuio])
        else:
            log.info("iscsi: iscsiuio not found.")

        # run the daemon
        util.run_program([ISCSID])
        time.sleep(1)

        self._start_ibft()
        self.started = True

    def discover(self, ipaddr, port="3260", username=None, password=None,
                 r_username=None, r_password=None):
        """
        Discover iSCSI nodes on the target available for login.

        If we are logged in a node discovered for specified target
        do not do the discovery again as it can corrupt credentials
        stored for the node (set_auth and get_auth are using database
        in /var/lib/iscsi/nodes which is filled by discovery). Just
        return nodes obtained and stored in the first discovery
        instead.

        Returns list of nodes user can log in.
        """

        if not has_iscsi():
            raise IOError(_("iSCSI not available"))
        if self._initiator == "":
            raise ValueError(_("No initiator name set"))

        if self.active_nodes(TargetInfo(ipaddr, port)):
            log.debug("iSCSI: skipping discovery of %s:%s due to active nodes",
                      ipaddr, port)
        else:
            self.startup()
            auth_info = dict()
            if username:
                auth_info["username"] = GLib.Variant("s", username)
            if password:
                auth_info["password"] = GLib.Variant("s", password)
            if r_username:
                auth_info["reverse-username"] = GLib.Variant("s", r_username)
            if r_password:
                auth_info["reverse-password"] = GLib.Variant("s", r_password)

            args = GLib.Variant("(sqa{sv})", (ipaddr, int(port), auth_info))
            nodes, _n_nodes = self._call_initiator_method("DiscoverSendTargets", args)

            found_nodes = _to_node_infos(nodes)
            t_info = TargetInfo(ipaddr, port)
            self.discovered_targets[t_info] = []
            for node in found_nodes:
                self.discovered_targets[t_info].append(LoginInfo(node, False))
                log.debug("discovered iSCSI node: %s", node.name)

        # only return the nodes we are not logged into yet
        return [info.node for info in self.discovered_targets[TargetInfo(ipaddr, port)]
                if not info.logged_in]

    def log_into_node(self, node, username=None, password=None,
                      r_username=None, r_password=None):
        """
        :param node: node to log into
        :type node: :class:`NodeInfo`
        :param str username: username to use when logging in
        :param str password: password to use when logging in
        :param str r_username: r_username to use when logging in
        :param str r_password: r_password to use when logging in
        """

        rc = False  # assume failure
        msg = ""

        auth_info = dict()
        if username:
            auth_info["username"] = GLib.Variant("s", username)
        if password:
            auth_info["password"] = GLib.Variant("s", password)
        if r_username:
            auth_info["reverse-username"] = GLib.Variant("s", r_username)
        if r_password:
            auth_info["reverse-password"] = GLib.Variant("s", r_password)

        try:
            self._login(node, auth_info)
            rc = True
            log.info("iSCSI: logged into %s at %s:%s through %s",
                     node.name, node.address, node.port, node.iface)
            if not self._mark_node_active(node):
                log.error("iSCSI: node not found among discovered")
            if username:
                node.username = username
            if password:
                node.password = password
            if r_username:
                node.r_username = r_username
            if r_password:
                node.r_password = r_password
        except safe_dbus.DBusCallError as e:
            msg = str(e)
            log.warning("iSCSI: could not log into %s: %s", node.name, msg)

        return (rc, msg)

    def add_target(self, ipaddr, port="3260", user=None, pw=None,
                   user_in=None, pw_in=None, target=None, iface=None,
                   discover_user=None, discover_pw=None,
                   discover_user_in=None, discover_pw_in=None):
        """
        Connect to iSCSI server specified by IP address and port
        and add all targets found on the server and authenticate if necessary.
        If the target parameter is set, connect only to this target.

        NOTE: the iSCSI target can have two sets of different authentication
              credentials - one for discovery and one for logging into nodes

        :param str ipaddr: target IP address
        :param str port: target port
        :param user: CHAP username for node login
        :type user: str or NoneType
        :param pw: CHAP password for node login
        :type pw: str or NoneType
        :param user_in: reverse CHAP username for node login
        :type user: str or NoneType
        :param pw_in: reverse CHAP password for node login
        :type pw_in: str or NoneType
        :param target: only add this target (if present)
        :type target: str or NoneType
        :param iface: interface to use
        :type iface: str or NoneType
        :param discover_user: CHAP username for discovery
        :type discover_user: str or NoneType
        :param discover_pw: CHAP password for discovery
        :type discover_pw: str or NoneType
        :param discover_user_in: reverse CHAP username for discovery
        :type discover_user: str or NoneType
        :param discover_pw_in: reverse CHAP password for discovery
        :type discover_pw_in: str or NoneType
        """

        found = 0
        logged_in = 0

        found_nodes = self.discover(ipaddr, port, discover_user, discover_pw,
                                    discover_user_in, discover_pw_in)
        if found_nodes is None:
            raise IOError(_("No iSCSI nodes discovered"))

        for node in found_nodes:
            if target and target != node.name:
                log.debug("iscsi: skipping logging to iscsi node '%s'", node.name)
                continue
            if iface:
                node_net_iface = self.ifaces.get(node.iface, node.iface)
                if iface != node_net_iface:
                    log.debug("iscsi: skipping logging to iscsi node '%s' via %s",
                              node.name, node_net_iface)
                    continue

            found = found + 1

            (rc, _msg) = self.log_into_node(node, user, pw, user_in, pw_in)
            if rc:
                logged_in = logged_in + 1

        if found == 0:
            raise IOError(_("No new iSCSI nodes discovered"))

        if logged_in == 0:
            raise IOError(_("Could not log in to any of the discovered nodes"))

        self.stabilize()

    def write(self, root, storage=None):  # pylint: disable=unused-argument
        if not self.initiator_set:
            return

        # copy "db" files.  *sigh*
        if os.path.isdir(root + "/var/lib/iscsi"):
            shutil.rmtree(root + "/var/lib/iscsi")
        if os.path.isdir("/var/lib/iscsi"):
            shutil.copytree("/var/lib/iscsi", root + "/var/lib/iscsi",
                            symlinks=True)

        # copy the initiator file too
        if not os.path.isdir(root + "/etc/iscsi"):
            os.makedirs(root + "/etc/iscsi", 0o755)
        shutil.copyfile(INITIATOR_FILE, root + INITIATOR_FILE)

    def get_node(self, name, address, port, iface):
        for node in self.active_nodes():
            if node.name == name and node.address == address and \
               node.port == int(port) and node.iface == iface:
                return node

        return None

    def get_node_disks(self, node, storage):
        node_disks = []
        iscsi_disks = (d for d in storage.devices if d.type == "iscsi")
        for disk in iscsi_disks:
            if disk.node == node:
                node_disks.append(disk)

        return node_disks


# Create iscsi singleton
iscsi = iSCSI()
""" An instance of :class:`iSCSI` """

# vim:tw=78:ts=4:et:sw=4
