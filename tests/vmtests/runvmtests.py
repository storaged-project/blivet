import argparse
import libvirt
import paramiko
import sys
import time
from contextlib import contextmanager


TESTS = ["tests.vmtests.blivet_reset_vmtest.LVMTestCase",
         "tests.vmtests.blivet_reset_vmtest.LVMSnapShotTestCase",
         "tests.vmtests.blivet_reset_vmtest.LVMThinpTestCase",
         "tests.vmtests.blivet_reset_vmtest.LVMThinSnapShotTestCase",
         "tests.vmtests.blivet_reset_vmtest.LVMRaidTestCase",
         "tests.vmtests.blivet_reset_vmtest.MDRaid0TestCase",
         "tests.vmtests.blivet_reset_vmtest.LVMOnMDTestCase"]

SNAP_NAME = "snapshot"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=str, help="Git repo with tests", required=True)
    parser.add_argument("--branch", type=str, help="Git branch to test", required=True)
    parser.add_argument("--connection", type=str, help="Libvirt connection URI", required=True)
    parser.add_argument("--name", type=str, help="Name of the virtual machine", required=True)
    parser.add_argument("--ip", type=str, help="IP adress of the virtual machine", required=True)
    parser.add_argument("--passphrase", type=str, help="Root passphrase for the virtual machine", required=True)
    args = parser.parse_args()
    return args


@contextmanager
def virtual_machine(cmd_args):
    try:
        conn = libvirt.open(cmd_args.connection)
    except libvirt.libvirtError as e:
        raise RuntimeError("Failed to open connection:\n%s", str(e))

    try:
        dom = conn.lookupByName(cmd_args.name)
    except libvirt.libvirtError:
        raise RuntimeError("Virtual machine %s not found", cmd_args.name)

    snapshots = dom.snapshotListNames()
    if SNAP_NAME in snapshots:
        try:
            snap = dom.snapshotLookupByName(SNAP_NAME)
            snap.delete()
        except libvirt.libvirtError as e:
            raise RuntimeError("Failed to delete snapshot:\n %s", str(e))

    # start the VM
    try:
        dom.create()
    except libvirt.libvirtError as e:
        raise RuntimeError("Failed to start virtual machine:%s", str(e))

    # wait for virtual machine to boot and create snapshot
    time.sleep(120)
    with ssh_connection(cmd_args):
        try:
            snap_xml = "<domainsnapshot><name>%s</name></domainsnapshot>" % SNAP_NAME
            dom.snapshotCreateXML(snap_xml)
        except libvirt.libvirtError as e:
            raise RuntimeError("Failed to create snapshot:\n%s.", str(e))

    yield dom

    # stop the VM
    try:
        dom.destroy()
    except libvirt.libvirtError as e:
        raise RuntimeError("Failed to stop virtual machine:%s", str(e))

    # remove the snapshot
    try:
        snap = dom.snapshotLookupByName(SNAP_NAME)
        snap.delete()
    except libvirt.libvirtError as e:
        raise RuntimeError("Failed to delete snapshot:\n %s", str(e))


@contextmanager
def ssh_connection(cmd_args):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(cmd_args.ip, username="root", password=cmd_args.passphrase)
    except paramiko.AuthenticationException:
        raise RuntimeError("Authentication failed while trying to connect to virtual machine.")

    yield ssh

    ssh.close()


def run_tests(cmd_args):
    """ Run tests in the VM

        :param cmd_args: parsed args from command line

    """

    with virtual_machine(cmd_args) as virt:
        num_errors = 0
        for test in TESTS:
            with ssh_connection(cmd_args) as ssh:
                _stdin, stdout, stderr = ssh.exec_command("git clone %s" % cmd_args.repo)
                if stdout.channel.recv_exit_status() != 0:
                    raise RuntimeError("Failed to clone test repository.")

                cmd = "export VM_ENVIRONMENT=1 && cd blivet && git checkout %s && \
                       PYTHONPATH=. python3 -m unittest %s" % (cmd_args.branch, test)
                _stdin, stdout, stderr = ssh.exec_command(cmd)
                print(stdout.read().decode("utf-8"))
                print(stderr.read().decode("utf-8"))

                ret = stdout.channel.recv_exit_status()
                if ret != 0:
                    num_errors += 1

            try:
                snap = virt.snapshotLookupByName(SNAP_NAME)
                virt.revertToSnapshot(snap)
            except libvirt.libvirtError as e:
                raise RuntimeError("Failed to revert to snapshot:\n %s", str(e))

    print("================================")
    print("Ran %d tests. %d failures/errors." % (len(TESTS), num_errors))
    print("================================")

    return 0 if num_errors == 0 else 1


def main():
    cmd_args = parse_args()
    ret = run_tests(cmd_args)
    sys.exit(ret)

if __name__ == "__main__":
    main()
