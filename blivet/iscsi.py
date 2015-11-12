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
from multiprocessing import Process, Pipe
import os
import logging
import shutil
import time
import itertools
log = logging.getLogger("blivet")

has_libiscsi = True
try:
    import libiscsi
except ImportError:
    has_libiscsi = False

# Note that stage2 copies all files under /sbin to /usr/sbin
ISCSID=""
INITIATOR_FILE="/etc/iscsi/initiatorname.iscsi"

ISCSI_MODULES=['cxgb3i', 'bnx2i', 'be2iscsi']

def has_iscsi():
    global ISCSID

    if not os.access("/sys/module/iscsi_tcp", os.X_OK):
        return False

    if not ISCSID:
        location = util.find_program_in_path("iscsid")
        if not location:
            return False
        ISCSID = location
        log.info("ISCSID is %s", ISCSID)

    return True


def _call_discover_targets(conn_pipe, ipaddr, port, authinfo):
    """ Function to separate iscsi :py:func:`libiscsi.discover_sendtargets` call to it's own process.

        The call must be started on special process because the :py:mod:`libiscsi`
        library is not thread safe. When thread is used or it's called on
        main thread the main thread will freeze.

        Also the discover is about four times slower (only for timeout)
        this is caused by signals which are delivered to bad (python)
        thread instead of C library thread.

        .. note::

            To transfer data to main process ``conn_pipe`` (write only) is used.
            Pipe returns tuple (ok, data).

            * ``ok``: True if everything was ok
            * ``data``: Dictionary with :py:func:`libiscsi.node` parameters if ``ok`` was True.
              Exception if ``ok`` was False

        :param conn_pipe: Pipe to the main process (write only)
        :type conn_pipe: :py:func:`multiprocessing.Pipe`
        :param str ipaddr: target IP address
        :param str port: target port
        :param authinfo: CHAP authentication data for node login
        :type authinfo: Object returned by :py:func:`libiscsi.chapAuthInfo` or None
    """
    try:
        found_nodes = libiscsi.discover_sendtargets(address=ipaddr,
                                                    port=int(port),
                                                    authinfo=authinfo)
        if found_nodes is None:
            found_nodes = []

    except IOError as ex:
        conn_pipe.send((False, ex))
        conn_pipe.close()
        return

    nodes = []

    # the node object is not pickable so it can't be send with pipe
    # TODO: change libiscsi.node to pickable object
    for node in found_nodes:
        nodes.append({'name': node.name,
                     'tpgt': node.tpgt,
                     'address': node.address,
                     'port': node.port,
                     'iface': node.iface})

    conn_pipe.send((True, nodes))


class iscsi(object):
    """ iSCSI utility class.

        This class will automatically discover and login to iBFT (or
        other firmware) configured iscsi devices when the startup() method
        gets called. It can also be used to manually configure iscsi devices
        through the addTarget() method.

        As this class needs to make sure certain things like starting iscsid
        and logging in to firmware discovered disks only happens once
        and as it keeps a global list of all iSCSI devices it is implemented as
        a Singleton.

        .. warning::
            Since this is a singleton class, calling deepcopy() on the instance
            just returns ``self`` with no copy being created.
    """

    def __init__(self):
        # Dictionary of discovered targets containing list of (node,
        # logged_in) tuples.
        self.discovered_targets = {}
        # This list contains nodes discovered through iBFT (or other firmware)
        self.ibftNodes = []
        self._initiator = ""
        self.initiatorSet = False
        self.started = False
        self.ifaces = {}

        if flags.ibft:
            try:
                initiatorname = libiscsi.get_firmware_initiator_name()
                self._initiator = initiatorname
                self.initiatorSet = True
            except Exception: # pylint: disable=broad-except
                log_exception_info(fmt_str="failed to get initiator name from iscsi firmware")

    # So that users can write iscsi() to get the singleton instance
    def __call__(self):
        return self

    def __deepcopy__(self, memo_dict):
        # pylint: disable=unused-argument
        return self

    def _getInitiator(self):
        if self._initiator != "":
            return self._initiator

        return util.capture_output(["iscsi-iname"]).strip()

    def _setInitiator(self, val):
        if self.initiatorSet and val != self._initiator:
            raise ValueError(_("Unable to change iSCSI initiator name once set"))
        if len(val) == 0:
            raise ValueError(_("Must provide an iSCSI initiator name"))
        self._initiator = val

    initiator = property(_getInitiator, _setInitiator)

    def active_nodes(self, target=None):
        """Nodes logged in to"""
        if target:
            return [node for (node, logged_in) in
                    self.discovered_targets.get(target, [])
                    if logged_in]
        else:
            return [node for (node, logged_in) in
                    itertools.chain(*list(self.discovered_targets.values()))
                    if logged_in] + self.ibftNodes

    def _getMode(self):
        if not self.active_nodes():
            return "none"
        if self.ifaces:
            return "bind"
        else:
            return "default"

    mode = property(_getMode)

    def _mark_node_active(self, node, active=True):
        """Mark node as one logged in to

           Returns False if not found
        """
        for target_nodes in self.discovered_targets.values():
            for nodeinfo in target_nodes:
                if nodeinfo[0] is node:
                    nodeinfo[1] = active
                    return True
        return False


    def _startIBFT(self):
        if not flags.ibft:
            return

        try:
            found_nodes = libiscsi.discover_firmware()
        except Exception: # pylint: disable=broad-except
            log_exception_info(log.info, "iscsi: No IBFT info found.")
            # an exception here means there is no ibft firmware, just return
            return

        for node in found_nodes:
            try:
                node.login()
                log.info("iscsi IBFT: logged into %s at %s:%s through %s",
                    node.name, node.address, node.port, node.iface)
                self.ibftNodes.append(node)
            except IOError as e:
                log.error("iSCSI: could not log into ibft %s at %s:%s through %s: %s",
                         node.name, node.address, node.port, node.iface,
                         str(e))

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
            #iscsiadm -m iface -I iface0 --op=new
            util.run_program(["iscsiadm", "-m", "iface",
                              "-I", iscsi_iface_name, "--op=new"])
            #iscsiadm -m iface -I iface0 --op=update -n iface.net_ifacename -v eth0
            util.run_program(["iscsiadm", "-m", "iface",
                              "-I", iscsi_iface_name, "--op=update",
                              "-n", "iface.net_ifacename", "-v", iface])

            self.ifaces[iscsi_iface_name] = iface
            log.debug("created_interface %s:%s", iscsi_iface_name, iface)

    def delete_interfaces(self):
        if not self.ifaces:
            return None
        for iscsi_iface_name in self.ifaces:
            #iscsiadm -m iface -I iface0 --op=delete
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

        log.debug("Setting up %s", INITIATOR_FILE)
        log.info("iSCSI initiator name %s", self.initiator)
        if os.path.exists(INITIATOR_FILE):
            os.unlink(INITIATOR_FILE)
        if not os.path.isdir("/etc/iscsi"):
            os.makedirs("/etc/iscsi", 0o755)
        fd = os.open(INITIATOR_FILE, os.O_RDWR | os.O_CREAT)
        os.write(fd, "InitiatorName=%s\n" %(self.initiator))
        os.close(fd)
        self.initiatorSet = True

        for fulldir in (os.path.join("/var/lib/iscsi", d) for d in \
           ['ifaces','isns','nodes','send_targets','slp','static']):
            if not os.path.isdir(fulldir):
                os.makedirs(fulldir, 0o755)

        log.info("iSCSI startup")
        util.run_program(['modprobe', '-a'] + ISCSI_MODULES)
        # iscsiuio is needed by Broadcom offload cards (bnx2i). Currently
        # not present in iscsi-initiator-utils for Fedora.
        try:
            iscsiuio = util.find_program_in_path('iscsiuio',
                                                   raise_on_error=True)
        except RuntimeError:
            log.info("iscsi: iscsiuio not found.")
        else:
            log.debug("iscsi: iscsiuio is at %s", iscsiuio)
            util.run_program([iscsiuio])
        # run the daemon
        util.run_program([ISCSID])
        time.sleep(1)

        self._startIBFT()
        self.started = True

    def discover(self, ipaddr, port="3260", username=None, password=None,
                 r_username=None, r_password=None):
        """
        Discover iSCSI nodes on the target available for login.

        If we are logged in a node discovered for specified target
        do not do the discovery again as it can corrupt credentials
        stored for the node (setAuth and getAuth are using database
        in /var/lib/iscsi/nodes which is filled by discovery). Just
        return nodes obtained and stored in the first discovery
        instead.

        Returns list of nodes user can log in.
        """
        authinfo = None

        if not has_iscsi():
            raise IOError(_("iSCSI not available"))
        if self._initiator == "":
            raise ValueError(_("No initiator name set"))

        if self.active_nodes((ipaddr, port)):
            log.debug("iSCSI: skipping discovery of %s:%s due to active nodes",
                      ipaddr, port)
        else:
            if username or password or r_username or r_password:
                # Note may raise a ValueError
                authinfo = libiscsi.chapAuthInfo(username=username,
                                                 password=password,
                                                 reverse_username=r_username,
                                                 reverse_password=r_password)
            self.startup()

            # start libiscsi discover_sendtargets in a new process
            # threads can't be used here because the libiscsi library
            # using signals internally which are send to bad thread
            (con_recv, con_write) = Pipe(False)
            p = Process(target=_call_discover_targets, args=(con_write,
                                                             ipaddr,
                                                             port,
                                                             authinfo, ))
            p.start()

            try:
                (ok, data) = con_recv.recv()
                if not ok:
                    log.debug("iSCSI: exception raised when "
                              "discover_sendtargets process called: %s",
                              str(data))
            except EOFError:
                ok = False
                log.error("iSCSI: can't receive response from "
                          "_call_discover_targets")

            p.join()

            # convert dictionary back to iscsi nodes object
            if ok:
                found_nodes = []
                for node in data:
                    found_nodes.append(libiscsi.node(**node))
            else:
                return []

            self.discovered_targets[(ipaddr, port)] = []
            for node in found_nodes:
                self.discovered_targets[(ipaddr, port)].append([node, False])
                log.debug("discovered iSCSI node: %s, %s:%s, %s",
                          node.name, node.address, node.port, node.iface)

        # only return the nodes we are not logged into yet
        return [node for (node, logged_in) in
                self.discovered_targets[(ipaddr, port)]
                if not logged_in]

    def log_into_node(self, node, username=None, password=None,
                  r_username=None, r_password=None):
        """
        Raises IOError.
        """
        rc = False # assume failure
        msg = ""

        try:
            authinfo = None
            if username or password or r_username or r_password:
                # may raise a ValueError
                authinfo = libiscsi.chapAuthInfo(username=username,
                                                 password=password,
                                                 reverse_username=r_username,
                                                 reverse_password=r_password)
            node.setAuth(authinfo)
            node.login()
            rc = True
            log.info("iSCSI: logged into %s at %s:%s through %s",
                    node.name, node.address, node.port, node.iface)
            if not self._mark_node_active(node):
                log.error("iSCSI: node not found among discovered")
        except (IOError, ValueError) as e:
            msg = str(e)
            log.warning("iSCSI: could not log into %s at %s:%s through %s: %s",
                         node.name, node.address, node.port, node.iface, msg)

        return (rc, msg)

    def addTarget(self, ipaddr, port="3260", user=None, pw=None,
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
        if found_nodes == None:
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
                logged_in = logged_in +1

        if found == 0:
            raise IOError(_("No new iSCSI nodes discovered"))

        if logged_in == 0:
            raise IOError(_("Could not log in to any of the discovered nodes"))

        self.stabilize()

    def write(self, root, storage):
        if not self.initiatorSet:
            return

        # set iscsi nodes to autostart
        rootdev = storage.rootDevice
        for node in self.active_nodes():
            autostart = True
            disks = self.getNodeDisks(node, storage)
            for disk in disks:
                # nodes used for root get started by the initrd
                if rootdev.dependsOn(disk):
                    autostart = False

            if autostart:
                node.setParameter("node.startup", "automatic")

        if not os.path.isdir(root + "/etc/iscsi"):
            os.makedirs(root + "/etc/iscsi", 0o755)
        fd = os.open(root + INITIATOR_FILE, os.O_RDWR | os.O_CREAT)
        os.write(fd, "InitiatorName=%s\n" %(self.initiator))
        os.close(fd)

        # copy "db" files.  *sigh*
        if os.path.isdir(root + "/var/lib/iscsi"):
            shutil.rmtree(root + "/var/lib/iscsi")
        if os.path.isdir("/var/lib/iscsi"):
            shutil.copytree("/var/lib/iscsi", root + "/var/lib/iscsi",
                            symlinks=True)

    def getNode(self, name, address, port, iface):
        for node in self.active_nodes():
            if node.name == name and node.address == address and \
               node.port == int(port) and node.iface == iface:
                return node

        return None

    def getNodeDisks(self, node, storage):
        nodeDisks = []
        iscsiDisks = storage.devicetree.getDevicesByType("iscsi")
        for disk in iscsiDisks:
            if disk.node == node:
                nodeDisks.append(disk)

        return nodeDisks

# Create iscsi singleton
iscsi = iscsi()

# vim:tw=78:ts=4:et:sw=4
