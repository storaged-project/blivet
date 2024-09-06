Running VM tests
================

The VM tests are intended to run against a libvirt managed KVM
virtual machine, running a Live OS with two unprovisioned
disks present. A suitable environment can be created using
the virt-install program and Fedora Workstation Live CD
media. As root follow the steps::

  $ cd /var/lib/libvirt/images
  $ wget https://fedora.mirrorservice.org/fedora/linux/releases/36/Workstation/x86_64/iso/Fedora-Workstation-Live-x86_64-36-1.5.iso
  $ virt-install \
      --cdrom /var/lib/libvirt/images/Fedora-Workstation-Live-x86_64-36-1.5.iso \
      --name f36live \
      --memory 2000 \
      --noautoconsole \
      --vnc \
      --disk /var/lib/libvirt/images/f37livedata1.img,size=10 \
      --disk /var/lib/libvirt/images/f37livedata2.img,size=10

Connect to this running VM using virt-viewer from your desktop::

  $ virt-viewer -c qemu:///system f36live

when the live environment is ready a few quick configuration
steps are needed, from a terminal window in the guest:

* Edit ``/etc/ssh/sshd_config`` to set ``PermitRootLogin yes``
* Start SH with ``systemctl start sshd``
* Run ``passwd`` to set a root password

Note that if the VM is shutoff these steps will need repeating
since the live CD environment is stateless.

Back in the host OS, optionally deploy an SSH key to the VM
to avoid the need to provide a password when running tests::

  $ ssh-copy-id f36live

Note the above assumes that the ``libvirt-nss`` package is
installed  and ``libvirt_guest`` added to ``hosts:`` in
``/etc/nsswitch.conf`` to provide DNS/IP resolution based
on the guest VM name.

With those setup steps completed, the tests can be run using::

  $ python ./tests/vmtests/runvmtests.py \
      --connection qemu:///system \
      --repo https://github.com/<YOUR-USERNAME>/blivet \
      --branch <GIT-BRANCH-TO-TEST> \
      --name f36live \
      --ip f36live

The ``runvmtests.py`` script will save and restore snapshots
of the guest VM memory and disk state either side of each
test.  If a test fails, the ``--test`` arg takes the name of
a single test class to run.
