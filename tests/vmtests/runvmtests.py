import argparse
import logging
import libvirt
import paramiko
import re
import sys
import time
from contextlib import contextmanager


log = logging.getLogger()

TESTS = ["tests.vmtests.blivet_reset_vmtest.LVMTestCase",
         "tests.vmtests.blivet_reset_vmtest.LVMSnapShotTestCase",
         "tests.vmtests.blivet_reset_vmtest.LVMThinpTestCase",
         "tests.vmtests.blivet_reset_vmtest.LVMThinSnapShotTestCase",
         "tests.vmtests.blivet_reset_vmtest.LVMRaidTestCase",
         "tests.vmtests.blivet_reset_vmtest.MDRaid0TestCase",
         "tests.vmtests.blivet_reset_vmtest.LVMOnMDTestCase",
         "tests.vmtests.blivet_reset_vmtest.LVMVDOTestCase",
         "tests.vmtests.blivet_reset_vmtest.StratisTestCase",
         "tests.vmtests.gpt_test.GPTDiscoverableTestCase",
         "tests.vmtests.gpt_test.GPTNonDiscoverableTestCase"]

SNAP_NAME = "snapshot"


def parse_args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", type=str, help="Git repo with tests", required=True)
    parser.add_argument("--branch", type=str, help="Git branch to test", required=True)
    parser.add_argument("--connection", type=str, help="Libvirt connection URI", required=True)
    parser.add_argument("--name", type=str, help="Name of the virtual machine", required=True)
    parser.add_argument("--ip", type=str, help="IP address of the virtual machine", required=True)
    parser.add_argument("--vmpass", type=str, help="Root passphrase for the virtual machine", required=False)
    parser.add_argument("--virtpass", type=str, help="Root passphrase for the libvirt host", required=False)
    parser.add_argument("--verbose", "-v", action='store_true', help="Display verbose information")
    parser.add_argument("--debug", "-d", action='store_true', help="Display debugging information")
    parser.add_argument("--test", "-t", help="Filter test classes to PATTERN")
    parser.add_argument("--logs", "-l", action='store_true', help="Capture and save blivet.log per failed test")
    args = parser.parse_args()
    return args


def request_cred(credentials, cmd_args):
    for credential in credentials:
        if credential[0] == libvirt.VIR_CRED_AUTHNAME:
            credential[4] = "root"
        elif credential[0] == libvirt.VIR_CRED_PASSPHRASE:
            credential[4] = cmd_args.virtpass
    return 0


@contextmanager
def virtual_machine(cmd_args):
    auth = [[libvirt.VIR_CRED_AUTHNAME, libvirt.VIR_CRED_PASSPHRASE], request_cred, None]
    try:
        log.info("Connecting to libvirt '%s'", cmd_args.connection)
        conn = libvirt.openAuth(cmd_args.connection, auth, 0)
    except libvirt.libvirtError as e:
        raise RuntimeError("Failed to open connection:\n%s" % str(e))

    try:
        log.info("Finding VM '%s'", cmd_args.name)
        dom = conn.lookupByName(cmd_args.name)
    except libvirt.libvirtError:
        raise RuntimeError("Virtual machine %s not found" % cmd_args.name)

    snapshots = dom.snapshotListNames()
    if SNAP_NAME in snapshots:
        try:
            log.info("Deleting snapshot '%s'", SNAP_NAME)
            snap = dom.snapshotLookupByName(SNAP_NAME)
            snap.delete()
        except libvirt.libvirtError as e:
            raise RuntimeError("Failed to delete snapshot:\n %s" % str(e))

    # start the VM
    wasRunning = dom.isActive()
    if not wasRunning:
        try:
            log.info("Starting VM '%s'", cmd_args.name)
            dom.create()
        except libvirt.libvirtError as e:
            raise RuntimeError("Failed to start virtual machine:%s" % str(e))

        # wait for virtual machine to boot and create snapshot
        log.info("Waiting 120 seconds for VM  '%s' to boot", cmd_args.name)
        time.sleep(120)

    with ssh_connection(cmd_args):
        log.info("Connected to SSH port in VM '%s'", cmd_args.name)
        try:
            snap_xml = "<domainsnapshot><name>%s</name></domainsnapshot>" % SNAP_NAME
            log.info("Creating snapshot of VM '%s'", cmd_args.name)
            dom.snapshotCreateXML(snap_xml)
        except libvirt.libvirtError as e:
            raise RuntimeError("Failed to create snapshot:\n%s." % str(e))

    yield dom

    if not wasRunning:
        # stop the VM
        try:
            log.info("Powering off VM '%s'", cmd_args.name)
            dom.destroy()
        except libvirt.libvirtError as e:
            raise RuntimeError("Failed to stop virtual machine:%s" % str(e))

    # remove the snapshot
    try:
        log.info("Deleting snapshot '%s' in VM '%s'", SNAP_NAME, cmd_args.name)
        snap = dom.snapshotLookupByName(SNAP_NAME)
        snap.delete()
    except libvirt.libvirtError as e:
        raise RuntimeError("Failed to delete snapshot:\n %s" % str(e))


@contextmanager
def ssh_connection(cmd_args):
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())

    try:
        ssh.connect(cmd_args.ip, username="root", password=cmd_args.vmpass)
    except paramiko.AuthenticationException:
        raise RuntimeError("Authentication failed while trying to connect to virtual machine.")

    yield ssh

    ssh.close()


def run_tests(cmd_args):
    """ Run tests in the VM

        :param cmd_args: parsed args from command line

    """

    pattern = None
    if cmd_args.test is not None:
        pattern = re.compile(cmd_args.test)

    with virtual_machine(cmd_args) as virt:
        test_results = []
        fails = errors = skips = 0
        for test in TESTS:
            if pattern is not None and not pattern.search(test):
                log.info("Skipping test '%s' in VM '%s'", test, cmd_args.name)
                continue
            log.info("Running test '%s' in VM '%s'", test, cmd_args.name)
            with ssh_connection(cmd_args) as ssh:
                # clone the repository with tests
                _stdin, stdout, stderr = ssh.exec_command("git clone %s" % cmd_args.repo)
                if stdout.channel.recv_exit_status() != 0:
                    raise RuntimeError("Failed to clone test repository.")

                # switch to selected branch
                _stdin, stdout, stderr = ssh.exec_command("cd blivet && git checkout %s" % cmd_args.branch)
                if stdout.channel.recv_exit_status() != 0:
                    raise RuntimeError("Failed to switch to branch %s.\nOutput:\n%s\n%s" %
                                       (cmd_args.branch, stdout.read().decode("utf-8"),
                                        stderr.read().decode("utf-8")))

                # run the tests
                cmd = "export VM_ENVIRONMENT=1 && cd blivet && \
                       PYTHONPATH=. python3 -m unittest %s" % test
                _stdin, stdout, stderr = ssh.exec_command(cmd)
                out = stdout.read().decode("utf-8")
                err = stderr.read().decode("utf-8")
                ret = stdout.channel.recv_exit_status()

                print(out)
                print(err)

                if ret != 0 and cmd_args.logs:
                    _stdin, stdout, _stderr = ssh.exec_command("cat /tmp/blivet.log")
                    out = stdout.read().decode("utf-8")

                    logfile = "blivet-" + test + ".log"
                    with open(logfile, "w") as fh:
                        print(out, file=fh)

                # save the result
                if ret != 0:
                    if "failures=" in err:
                        test_results.append((test, "FAILED"))
                        fails += 1
                    elif "errors=" in err:
                        test_results.append((test, "ERROR"))
                        errors += 1
                else:
                    if "skipped=" in err:
                        test_results.append((test, "SKIPPED"))
                        skips += 1
                    else:
                        test_results.append((test, "OK"))

            # revert to snapshot
            try:
                snap = virt.snapshotLookupByName(SNAP_NAME)
                virt.revertToSnapshot(snap)
            except libvirt.libvirtError as e:
                raise RuntimeError("Failed to revert to snapshot:\n %s" % str(e))

    # print combined result of all tests
    print("======================================================================")
    for result in test_results:
        print("%s: %s" % result)
    print("----------------------------------------------------------------------")
    print("Ran %d tests. %d failures, %d errors, %d skipped." % (len(test_results),
                                                                 fails, errors, skips))
    print("======================================================================")

    return 0 if (fails + errors) == 0 else 1


def main():
    cmd_args = parse_args()
    if cmd_args.debug or cmd_args.verbose:
        if cmd_args.debug:
            logging.basicConfig(level="DEBUG")
        else:
            logging.basicConfig(level="INFO")
        formatter = logging.Formatter("[%(levelname)s]: %(message)s")
        handler = log.handlers[0]
        handler.setFormatter(formatter)

    ret = run_tests(cmd_args)
    sys.exit(ret)


if __name__ == "__main__":
    main()
