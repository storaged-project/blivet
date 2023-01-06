# gpt.py
# GPT partitioning helpers
#
# Copyright (C) Red Hat, Inc.
#
# This copyrighted material is made available to anyone wishing to use,
# modify, copy, or redistribute it subject to the terms and conditions of
# the GNU General Public License v.2, or (at your option) any later version.
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY expressed or implied, including the implied warranties of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the GNU General
# Public License for more details.  You should have received a copy of the
# GNU General Public License along with this program; if not, write to the
# Free Software Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA
# 02110-1301, USA.  Any Red Hat trademarks that are incorporated in the
# source code or documentation are not subject to the GNU General Public
# License and may only be used or replicated with the express permission of
# Red Hat, Inc.
#

import uuid

from blivet.arch import get_arch
from blivet.errors import GPTVolUUIDError

GPT_VOL_ARCH_ROOT = "root"
GPT_VOL_ARCH_ROOT_VERITY = "root_verity"
GPT_VOL_ARCH_ROOT_VERITY_SIG = "root_verity_sig"
GPT_VOL_ARCH_USR = "usr"
GPT_VOL_ARCH_USR_VERITY = "usr_verity"
GPT_VOL_ARCH_USR_VERITY_SIG = "usr_verity_sig"

GPT_VOL_ESP = "esp"
GPT_VOL_XBOOTLDR = "xbootldr"
GPT_VOL_SWAP = "swap"
GPT_VOL_HOME = "home"
GPT_VOL_SRV = "srv"
GPT_VOL_VAR = "var"
GPT_VOL_TMP = "tmp"
GPT_VOL_USER_HOME = "user_home"
GPT_VOL_LINUX_GENERIC = "linux_generic"

_gpt_common_uuid = {
    GPT_VOL_ESP: uuid.UUID("c12a7328-f81f-11d2-ba4b-00a0c93ec93b"),
    GPT_VOL_XBOOTLDR: uuid.UUID("bc13c2ff-59e6-4262-a352-b275fd6f7172"),
    GPT_VOL_SWAP: uuid.UUID("0657fd6d-a4ab-43c4-84e5-0933c84b4f4f"),
    GPT_VOL_HOME: uuid.UUID("933ac7e1-2eb4-4f13-b844-0e14e2aef915"),
    GPT_VOL_SRV: uuid.UUID("3b8f8425-20e0-4f3b-907f-1a25a76f98e8"),
    GPT_VOL_VAR: uuid.UUID("4d21b016-b534-45c2-a9fb-5c16e091fd2d"),
    GPT_VOL_TMP: uuid.UUID("7ec6f557-3bc5-4aca-b293-16ef5df639d1"),
    GPT_VOL_USER_HOME: uuid.UUID("773f91ef-66d4-49b5-bd83-d683bf40ad16"),
    GPT_VOL_LINUX_GENERIC: uuid.UUID("0fc63daf-8483-4772-8e79-3d69d8477de4"),
}

_gpt_arch_uuid = {
    GPT_VOL_ARCH_ROOT: {
        "alpha": uuid.UUID("6523f8ae-3eb1-4e2a-a05a-18b695ae656f"),
        "arc": uuid.UUID("d27f46ed-2919-4cb8-bd25-9531f3c16534"),
        "arm": uuid.UUID("69dad710-2ce4-4e3c-b16c-21a1d49abed3"),
        "aarch64": uuid.UUID("b921b045-1df0-41c3-af44-4c6f280d3fae"),
        "i386": uuid.UUID("44479540-f297-41b2-9af7-d131d5f0458a"),
        "ia64": uuid.UUID("993d8d3d-f80e-4225-855a-9daf8ed7ea97"),
        "loongarch64": uuid.UUID("77055800-792c-4f94-b39a-98c91b762bb6"),
        "mips64el": uuid.UUID("700bda43-7a34-4507-b179-eeb93d7a7ca3"),
        "mipsel": uuid.UUID("37c58c8a-d913-4156-a25f-48b1b64e07f0"),
        "parisc": uuid.UUID("1aacdb3b-5444-4138-bd9e-e5c2239b2346"),
        "ppc": uuid.UUID("1de3f1ef-fa98-47b5-8dcd-4a860a654d78"),
        "ppc64": uuid.UUID("912ade1d-a839-4913-8964-a10eee08fbd2"),
        "ppc64el": uuid.UUID("c31c45e6-3f39-412e-80fb-4809c4980599"),
        "riscv32": uuid.UUID("60d5a7fe-8e7d-435c-b714-3dd8162144e1"),
        "riscv64": uuid.UUID("72ec70a6-cf74-40e6-bd49-4bda08e8f224"),
        "s390": uuid.UUID("08a7acea-624c-4a20-91e8-6e0fa67d23f9"),
        "s390x": uuid.UUID("5eead9a9-fe09-4a1e-a1d7-520d00531306"),
        "tilegx": uuid.UUID("c50cdd70-3862-4cc3-90e1-809a8c93ee2c"),
        "x86_64": uuid.UUID("4f68bce3-e8cd-4db1-96e7-fbcaf984b709"),
    },
    GPT_VOL_ARCH_ROOT_VERITY: {
        "alpha": uuid.UUID("fc56d9e9-e6e5-4c06-be32-e74407ce09a5"),
        "arc": uuid.UUID("24b2d975-0f97-4521-afa1-cd531e421b8d"),
        "arm": uuid.UUID("7386cdf2-203c-47a9-a498-f2ecce45a2d6"),
        "aarch64": uuid.UUID("df3300ce-d69f-4c92-978c-9bfb0f38d820"),
        "i386": uuid.UUID("d13c5d3b-b5d1-422a-b29f-9454fdc89d76"),
        "ia64": uuid.UUID("86ed10d5-b607-45bb-8957-d350f23d0571"),
        "loongarch64": uuid.UUID("f3393b22-e9af-4613-a948-9d3bfbd0c535"),
        "mips64el": uuid.UUID("16b417f8-3e06-4f57-8dd2-9b5232f41aa6"),
        "mipsel": uuid.UUID("d7d150d2-2a04-4a33-8f12-16651205ff7b"),
        "parisc": uuid.UUID("d212a430-fbc5-49f9-a983-a7feef2b8d0e"),
        "ppc": uuid.UUID("98cfe649-1588-46dc-b2f0-add147424925"),
        "ppc64": uuid.UUID("9225a9a3-3c19-4d89-b4f6-eeff88f17631"),
        "ppc64el": uuid.UUID("906bd944-4589-4aae-a4e4-dd983917446a"),
        "riscv32": uuid.UUID("ae0253be-1167-4007-ac68-43926c14c5de"),
        "riscv64": uuid.UUID("b6ed5582-440b-4209-b8da-5ff7c419ea3d"),
        "s390": uuid.UUID("7ac63b47-b25c-463b-8df8-b4a94e6c90e1"),
        "s390x": uuid.UUID("b325bfbe-c7be-4ab8-8357-139e652d2f6b"),
        "tilegx": uuid.UUID("966061ec-28e4-4b2e-b4a5-1f0a825a1d84"),
        "x86_64": uuid.UUID("2c7357ed-ebd2-46d9-aec1-23d437ec2bf5"),
    },
    GPT_VOL_ARCH_ROOT_VERITY_SIG: {
        "alpha": uuid.UUID("d46495b7-a053-414f-80f7-700c99921ef8"),
        "arc": uuid.UUID("143a70ba-cbd3-4f06-919f-6c05683a78bc"),
        "arm": uuid.UUID("42b0455f-eb11-491d-98d3-56145ba9d037"),
        "aarch64": uuid.UUID("6db69de6-29f4-4758-a7a5-962190f00ce3"),
        "i386": uuid.UUID("5996fc05-109c-48de-808b-23fa0830b676"),
        "ia64": uuid.UUID("e98b36ee-32ba-4882-9b12-0ce14655f46a"),
        "loongarch64": uuid.UUID("5afb67eb-ecc8-4f85-ae8e-ac1e7c50e7d0"),
        "mips64el": uuid.UUID("904e58ef-5c65-4a31-9c57-6af5fc7c5de7"),
        "mipsel": uuid.UUID("c919cc1f-4456-4eff-918c-f75e94525ca5"),
        "parisc": uuid.UUID("15de6170-65d3-431c-916e-b0dcd8393f25"),
        "ppc": uuid.UUID("1b31b5aa-add9-463a-b2ed-bd467fc857e7"),
        "ppc64": uuid.UUID("f5e2c20c-45b2-4ffa-bce9-2a60737e1aaf"),
        "ppc64el": uuid.UUID("d4a236e7-e873-4c07-bf1d-bf6cf7f1c3c6"),
        "riscv32": uuid.UUID("3a112a75-8729-4380-b4cf-764d79934448"),
        "riscv64": uuid.UUID("efe0f087-ea8d-4469-821a-4c2a96a8386a"),
        "s390": uuid.UUID("3482388e-4254-435a-a241-766a065f9960"),
        "s390x": uuid.UUID("c80187a5-73a3-491a-901a-017c3fa953e9"),
        "tilegx": uuid.UUID("b3671439-97b0-4a53-90f7-2d5a8f3ad47b"),
        "x86_64": uuid.UUID("41092b05-9fc8-4523-994f-2def0408b176"),
    },
    GPT_VOL_ARCH_USR: {
        "alpha": uuid.UUID("e18cf08c-33ec-4c0d-8246-c6c6fb3da024"),
        "arc": uuid.UUID("7978a683-6316-4922-bbee-38bff5a2fecc"),
        "arm": uuid.UUID("7d0359a3-02b3-4f0a-865c-654403e70625"),
        "aarch64": uuid.UUID("b0e01050-ee5f-4390-949a-9101b17104e9"),
        "i386": uuid.UUID("75250d76-8cc6-458e-bd66-bd47cc81a812"),
        "ia64": uuid.UUID("4301d2a6-4e3b-4b2a-bb94-9e0b2c4225ea"),
        "loongarch64": uuid.UUID("e611c702-575c-4cbe-9a46-434fa0bf7e3f"),
        "mips64el": uuid.UUID("c97c1f32-ba06-40b4-9f22-236061b08aa8"),
        "mipsel": uuid.UUID("0f4868e9-9952-4706-979f-3ed3a473e947"),
        "parisc": uuid.UUID("dc4a4480-6917-4262-a4ec-db9384949f25"),
        "ppc": uuid.UUID("7d14fec5-cc71-415d-9d6c-06bf0b3c3eaf"),
        "ppc64": uuid.UUID("2c9739e2-f068-46b3-9fd0-01c5a9afbcca"),
        "ppc64el": uuid.UUID("15bb03af-77e7-4d4a-b12b-c0d084f7491c"),
        "riscv32": uuid.UUID("b933fb22-5c3f-4f91-af90-e2bb0fa50702"),
        "riscv64": uuid.UUID("beaec34b-8442-439b-a40b-984381ed097d"),
        "s390": uuid.UUID("cd0f869b-d0fb-4ca0-b141-9ea87cc78d66"),
        "s390x": uuid.UUID("8a4f5770-50aa-4ed3-874a-99b710db6fea"),
        "tilegx": uuid.UUID("55497029-c7c1-44cc-aa39-815ed1558630"),
        "x86_64": uuid.UUID("8484680c-9521-48c6-9c11-b0720656f69e"),
    },
    GPT_VOL_ARCH_USR_VERITY: {
        "alpha": uuid.UUID("8cce0d25-c0d0-4a44-bd87-46331bf1df67"),
        "arc": uuid.UUID("fca0598c-d880-4591-8c16-4eda05c7347c"),
        "arm": uuid.UUID("c215d751-7bcd-4649-be90-6627490a4c05"),
        "aarch64": uuid.UUID("6e11a4e7-fbca-4ded-b9e9-e1a512bb664e"),
        "i386": uuid.UUID("8f461b0d-14ee-4e81-9aa9-049b6fb97abd"),
        "ia64": uuid.UUID("6a491e03-3be7-4545-8e38-83320e0ea880"),
        "loongarch64": uuid.UUID("f46b2c26-59ae-48f0-9106-c50ed47f673d"),
        "mips64el": uuid.UUID("3c3d61fe-b5f3-414d-bb71-8739a694a4ef"),
        "mipsel": uuid.UUID("46b98d8d-b55c-4e8f-aab3-37fca7f80752"),
        "parisc": uuid.UUID("5843d618-ec37-48d7-9f12-cea8e08768b2"),
        "ppc": uuid.UUID("df765d00-270e-49e5-bc75-f47bb2118b09"),
        "ppc64": uuid.UUID("bdb528a5-a259-475f-a87d-da53fa736a07"),
        "ppc64el": uuid.UUID("ee2b9983-21e8-4153-86d9-b6901a54d1ce"),
        "riscv32": uuid.UUID("cb1ee4e3-8cd0-4136-a0a4-aa61a32e8730"),
        "riscv64": uuid.UUID("8f1056be-9b05-47c4-81d6-be53128e5b54"),
        "s390": uuid.UUID("b663c618-e7bc-4d6d-90aa-11b756bb1797"),
        "s390x": uuid.UUID("31741cc4-1a2a-4111-a581-e00b447d2d06"),
        "tilegx": uuid.UUID("2fb4bf56-07fa-42da-8132-6b139f2026ae"),
        "x86_64": uuid.UUID("77ff5f63-e7b6-4633-acf4-1565b864c0e6"),
    },
    GPT_VOL_ARCH_USR_VERITY_SIG: {
        "alpha": uuid.UUID("5c6e1c76-076a-457a-a0fe-f3b4cd21ce6e"),
        "arc": uuid.UUID("94f9a9a1-9971-427a-a400-50cb297f0f35"),
        "arm": uuid.UUID("d7ff812f-37d1-4902-a810-d76ba57b975a"),
        "aarch64": uuid.UUID("c23ce4ff-44bd-4b00-b2d4-b41b3419e02a"),
        "i386": uuid.UUID("974a71c0-de41-43c3-be5d-5c5ccd1ad2c0"),
        "ia64": uuid.UUID("8de58bc2-2a43-460d-b14e-a76e4a17b47f"),
        "loongarch64": uuid.UUID("b024f315-d330-444c-8461-44bbde524e99"),
        "mips64el": uuid.UUID("f2c2c7ee-adcc-4351-b5c6-ee9816b66e16"),
        "mipsel": uuid.UUID("3e23ca0b-a4bc-4b4e-8087-5ab6a26aa8a9"),
        "parisc": uuid.UUID("450dd7d1-3224-45ec-9cf2-a43a346d71ee"),
        "ppc": uuid.UUID("7007891d-d371-4a80-86a4-5cb875b9302e"),
        "ppc64": uuid.UUID("0b888863-d7f8-4d9e-9766-239fce4d58af"),
        "ppc64el": uuid.UUID("c8bfbd1e-268e-4521-8bba-bf314c399557"),
        "riscv32": uuid.UUID("c3836a13-3137-45ba-b583-b16c50fe5eb4"),
        "riscv64": uuid.UUID("d2f9000a-7a18-453f-b5cd-4d32f77a7b32"),
        "s390": uuid.UUID("17440e4f-a8d0-467f-a46e-3912ae6ef2c5"),
        "s390x": uuid.UUID("3f324816-667b-46ae-86ee-9b0c0c6c11b4"),
        "tilegx": uuid.UUID("4ede75e2-6ccc-4cc8-b9c7-70334b087510"),
        "x86_64": uuid.UUID("e7bb33fb-06cf-4e81-8273-e543b413e2e2"),
    },
}


def gpt_part_uuid_for_volume(voltype, arch=None):
    """
    :param path: the volume type as a GPT_VOL constant
    :type path: str
    :param arch: the architecture of the target install, None to use host arch
    :type path: str

    :returns: the GPT partition type UUID or None
    :rtype: str

    Given a volume type defined by one of the GPT_VOL constants,
    determine if there is a well known GPT partition type UUID
    associated to allow the partition to be automatically mounted.

    The architecture must be canonicalized in accordance with the
    blivet.arch logic. Usually it can be omitted, to request use
    of the host architecture detected by blivet.arch.get_arch.
    """
    if voltype in _gpt_common_uuid:
        return _gpt_common_uuid[voltype]
    elif voltype not in _gpt_arch_uuid:
        raise GPTVolUUIDError("Unknown volume type")

    if arch is None:
        arch = get_arch()

    if arch not in _gpt_arch_uuid[voltype]:
        raise GPTVolUUIDError("Unknown architecture %s" % arch)

    return _gpt_arch_uuid[voltype][arch]


def gpt_part_uuid_for_mountpoint(path, arch=None):
    """
    :param path: the absolute path at which a filesystem is to be mounted
    :type path: str
    :param arch: the architecture of the target install, None to use host arch
    :type path: str

    :returns: the GPT partition type UUID or None
    :rtype: str

    Given an absolute path at which a filesystem is to be mounted,
    determine if there is a well known GPT partition type UUID
    associated to allow the partition to be automatically mounted.

    The architecture must be canonicalized in accordance with the
    blivet.arch logic. Usually it can be omitted, to request use
    of the host architecture detected by blivet.arch.get_arch.
    """
    mapping = {
        "/": GPT_VOL_ARCH_ROOT,
        "/usr": GPT_VOL_ARCH_USR,

        "/efi": GPT_VOL_ESP,
        "/boot/efi": GPT_VOL_ESP,
        "/boot": GPT_VOL_XBOOTLDR,
        "/home": GPT_VOL_HOME,
        "/var": GPT_VOL_VAR,
        "/srv": GPT_VOL_SRV,
        "/tmp": GPT_VOL_TMP,
    }

    if path not in mapping:
        return None

    return gpt_part_uuid_for_volume(mapping[path], arch)
