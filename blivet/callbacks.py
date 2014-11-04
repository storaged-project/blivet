#
# Copyright (C) 2014  Red Hat, Inc.
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
# Red Hat Author(s): Vratislav Podzimek <vpodzime@redhat.com>
#

"""
Module providing classes defining the callbacks used by Blivet and their
arguments.

"""

from collections import namedtuple

# A private namedtuple class with self-descriptive fields for passing callbacks
# to the blivet.doIt method. Each field should be populated with a function
# taking the matching CallbackTypeData (create_format_pre ->
# CreateFormatPreData, etc.)  object or None if no such callback is provided.
_CallbacksRegister = namedtuple("_CallbacksRegister",
                                ["create_format_pre",
                                 "create_format_post",
                                 "resize_format_pre",
                                 "resize_format_post",
                                 "wait_for_entropy"])

def create_new_callbacks_register(create_format_pre=None,
                                  create_format_post=None,
                                  resize_format_pre=None,
                                  resize_format_post=None,
                                  wait_for_entropy=None):
    """
    A function for creating a new opaque object holding the references to
    callbacks. The point of this function is to hide the implementation of such
    object and to provide default values for non-specified fields (e.g. newly
    added callbacks).

    :type create_format_pre: :class:`.CreateFormatPreData` -> NoneType
    :type create_format_post: :class:`.CreateFormatPostData` -> NoneType
    :type resize_format_pre: :class:`.ResizeFormatPreData` -> NoneType
    :type resize_format_post: :class:`.ResizeFormatPostData` -> NoneType
    :param wait_for_entropy: callback for waiting for enough entropy whose return
                             value indicates whether continuing regardless of
                             available entropy should be forced (True) or not (False)
    :type wait_for_entropy: :class:`.WaitForEntropyData` -> bool

    """

    return _CallbacksRegister(create_format_pre, create_format_post,
                              resize_format_pre, resize_format_post,
                              wait_for_entropy)

CreateFormatPreData = namedtuple("CreateFormatPreData",
                                 ["msg"])
CreateFormatPostData = namedtuple("CreateFormatPostData",
                                  ["msg"])
ResizeFormatPreData = namedtuple("ResizeFormatPreData",
                                 ["msg"])
ResizeFormatPostData = namedtuple("ResizeFormatPostData",
                                  ["msg"])
WaitForEntropyData = namedtuple("WaitForEntropyData",
                                ["msg", "min_entropy"])
