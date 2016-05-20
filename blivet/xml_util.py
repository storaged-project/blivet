from . import util
import xml.etree.ElementTree as ET
from socket import gethostname
import importlib
from collections import namedtuple
import inspect

import pdb

# debug
import traceback

################################################################################
##### BASIC FUNCTIONS
def create_basics():
    """
        This function creates root element and subelements that will be filled
        with Devices and Formats. Returns tuple: ET.Element and list
    """
    super_elems = []

    root_elem = ET.Element("Blivet-XML-Tools")
    super_elems.append(ET.SubElement(root_elem, "Devices"))
    super_elems.append(ET.SubElement(root_elem, "Formats"))
    super_elems.append(ET.SubElement(root_elem, "InternalDevices"))
    super_elems.append(ET.SubElement(root_elem, "Actions"))
    super_elems.append(ET.SubElement(root_elem, "DestroyedDevices"))
    super_elems.append(ET.SubElement(root_elem, "DestroyedFormats"))
    return (root_elem, super_elems)

def save_file(root_elem, dump_device=None, custom_name=None, rec_bool=False):
    """
        Saves a XML file upon specified criteria.
        Decides, if to save specific device data or whole Blivet.devices.
        Also, adds -recursive string to name and automatically appends ".xml".
    """
    # Get basic name, if custom, then custom
    final_name = gethostname().split(".")[0]
    if custom_name != None:
        final_name = custom_name
    # Append device name if specified
    if dump_device != None:
        final_name = final_name + dump_device
    # Will the name contain recursive?
    if rec_bool == True:
        final_name = final_name + "-recursive"
    # Finally, append extension
    final_name = final_name + ".xml"
    ET.ElementTree(root_elem).write(final_name, xml_declaration=True, encoding="utf-8")

def select_device(dev_list, dump_device, rec_bool):
    """
        Docstring
    """
    selected_devs = []
    for dev in dev_list:
        if dump_device in dev.name:
            selected_devs.append(dev)
            if rec_bool:
                break
    return selected_devs

def export_iterate(device_list, action_list, super_elems, master_root_elem):
    """
        :param list super_elems: List of super elements (under the root element)
    """
    # Define basic types
    disk_elems = []
    action_elems = []
    dev_counter = 0
    act_counter = 0

    for dev in device_list:
        if hasattr(dev, "to_xml"):
            dev_name = str(type(dev)).split("'")[1]
            disk_elems.append(ET.SubElement(super_elems[0], dev_name.split(".")[-1]))
            disk_elems[-1].set("type", dev_name)
            disk_elems[-1].set("ObjectID", str(getattr(dev, "id")))
            dev._to_xml_init(master_root_elem, devices_list=device_list)
            dev.to_xml()
            dev_counter = dev_counter + 1
    super_elems[0].set("Count", str(dev_counter))

    for action in action_list:
        act_name = str(type(action)).split("'")[1]
        action_elems.append(ET.SubElement(super_elems[3], act_name.split(".")[-1]))
        action_elems[-1].set("type", act_name)
        action_elems[-1].set("ObjectID", str(getattr(action, "id")))
        action._to_xml_init(master_root_elem, action_list=action_list, act_override=True, parent_override=action_elems[-1])
        action.to_xml()
        act_counter = act_counter + 1
    super_elems[3].set("Count", str(act_counter))



################################################################################
##### BASIC DEFINITION
class XMLUtils(util.ObjectID):
    def _to_xml_init(self, root_elem, devices_list=None, action_list=None, act_override=False,
                     object_override=None, parent_override=None, xml_done_ids=set(), xml_act_ids=set()):
        """
            :param ET.Element root_elem: Root element of the XML file
            or not.
            :param object_override: This is object that is not in devicetree.
            :param set xml_done_ids: set of IDs that are done to prevent duplicates
        """
        self.xml_root_elem = root_elem
        self.xml_devices_list = devices_list
        self.actions_list = action_list
        self.act_override = act_override

        self.device_elems = self.xml_root_elem[0]
        self.format_elems = self.xml_root_elem[1]
        self.intern_elems = self.xml_root_elem[2]

        # Action specific
        self.action_elems = self.xml_root_elem[3]
        self.desdev_elems = self.xml_root_elem[4]
        self.desfmt_elems = self.xml_root_elem[5]
        self.xml_iterables = {list, tuple, dict, "collections.OrderedDict",
                              "blivet.devices.lib.ParentList"}

        # Determine, what object to parse
        if object_override is None:
            self.xml_object = self
        else:
            self.xml_object = object_override

        # Determine where to store new elements
        self.xml_parent_elem = parent_override
        if self.xml_parent_elem is None:
            self.xml_parent_elem = self.device_elems[-1]

        self.xml_elems_list = [] # Elements will be stored here
        self.xml_attrs_done = set() # To prevent duplicates in xml_elems_list
        self.xml_done_ids = xml_done_ids # As above, but for ids
        self.xml_act_ids = xml_act_ids

        self.xml_attr_list = dir(self.xml_object) # List of attrs to gather

        # Subsection for allowed attributes and types
        self.xml_allowed_types = ["str", "int", "float", "set", "dict", "list",
                                  "blivet.size.Size", "tuple", "bool", "NoneType",
                                  "complex", "blivet.devices.", "blivet.formats.",
                                  "blivet.devicelibs.", "XMLFormat"]
        self.xml_unallowed_types = ["parted.", "LVMCacheStats"]
        self.xml_ign_attrs = ["passphrase", "xml", "abc", "dependencies", "dict",
                              "id", "_levels"]

################################################################################
##### Check ignored
    def _to_xml_check_igns(self, in_attr):
        if in_attr.startswith("__") or\
            self._to_xml_check_xml_ign_attrs(in_attr) or\
            not self._to_xml_check_allowed_types() or\
            self._to_xml_check_ign_types() or\
            in_attr in self.xml_attrs_done:
            return True
        else:
            return False

    def _to_xml_check_ign_types(self):
        for ig_type in self.xml_unallowed_types:
            if ig_type in self.xml_tmp_str_type:
                return True
        return False

    def _to_xml_check_allowed_types(self):
        for al_type in self.xml_allowed_types:
            if al_type in self.xml_tmp_str_type:
                return True
        return False

    # Check ignored in set
    def _to_xml_check_xml_ign_attrs(self, in_attr):
        for ig_attr in self.xml_ign_attrs:
            if ig_attr in in_attr:
                return True
        return False

    def _to_xml_check_ids(self):
        self.xml_tmp_id = getattr(self.xml_object, "id")
        if self.xml_tmp_id in self.xml_done_ids:
            return True

################################################################################
##### List parsing
    def _to_xml_parse_iterables(self, list_obj=None,
                                par_elem=None):
        """
            Parses anything, that can be iterated
        """
        # Set basic, before we can start
        sublist = []
        if list_obj is None:
            list_obj = self.xml_tmp_obj
        if par_elem is None:
            par_elem = self.xml_elems_list[-1]

        for item in list_obj:
            sublist.append(ET.SubElement(par_elem, "item"))
            self._to_xml_get_data(in_obj=item)
            # Check for dict
            if type(list_obj) is dict:
                sublist[-1].set("attr", item)
                item = list_obj.get(item)

            elif isinstance(self.xml_tmp_obj, tuple):
                sublist[-1].set("type", self.xml_tmp_str_type)
                item = dict(item.__dict__)
                sublist[-1].set("enforced", str(type(item)).split("'")[-2])

            # Reload data type
            self._to_xml_get_data(in_obj=item)
            self._to_xml_set_data_type(sublist[-1])
            # Check for any iterable
            if self.xml_tmp_type in self.xml_iterables or self.xml_tmp_str_type in self.xml_iterables:
                self._to_xml_parse_iterables(list_obj=self.xml_tmp_obj, par_elem=sublist[-1])

            else:
                self._to_xml_set_value(sublist[-1])
                if hasattr(self.xml_tmp_obj, "to_xml") and self.xml_tmp_obj not in self.xml_devices_list:
                    self._to_xml_get_data(in_obj=self.xml_tmp_obj)
                    self._to_xml_parse_device()


################################################################################
##### Parsing objects, that are under devices (mostly formats), that have to_xml
    def _to_xml_parse_sub_to_xml(self, parse_override=False, obj_override=None):
        """
            Parses a object, that also has to_xml() method. Basically it runs
            to_xml() on object has it.
        """
        if obj_override is not None:
            self.xml_tmp_obj = obj_override
        self._to_xml_set_data_type(self.xml_elems_list[-1])
        self._to_xml_set_value(self.xml_elems_list[-1])
        self.tmp_full_name = str(type(self.xml_tmp_obj)).split("'")[1]

        if self.act_override:
            ids_done = self.xml_act_ids
        else:
            ids_done = self.xml_done_ids

        if self.tmp_id not in ids_done:
            ids_done.add(self.tmp_id)

            # Import all required
            DeviceFormat = getattr(importlib.import_module("blivet.formats"), "DeviceFormat")
            Device = getattr(importlib.import_module("blivet.devices"), "Device")
            # For DeviceFormat
            if isinstance(self.xml_tmp_obj, DeviceFormat):
                self._to_xml_parse_format(act_override = self.act_override)
            # For Destroyed Device
            elif isinstance(self.xml_tmp_obj, Device) and self.act_override:
            # Device
                self._to_xml_parse_device(act_override=self.act_override)
            elif isinstance(self.xml_tmp_obj, Device) and not self.act_override:
                return
            # Anything else
            else:
                self._to_xml_parse_object()
        # Skip it, when ID is in xml_done_ids
        else:
            pass

    def _to_xml_parse_object(self):
        """
            Similar to format, this does the same like parse_format, but for devices.
        """
        self.xml_elems_list[-1].text = None
        self.xml_elems_list[-1].set("type", self.tmp_full_name)
        self.xml_elems_list[-1].set("ObjectID", str(self.tmp_id))

        new_obj_init = getattr(self.xml_tmp_obj, "_to_xml_init")
        new_obj_init = new_obj_init(self.xml_root_elem,
                                        object_override=self.xml_tmp_obj,
                                        parent_override=self.xml_elems_list[-1],
                                        xml_done_ids=self.xml_done_ids)
        # Finally, start parsing
        getattr(self.xml_tmp_obj, "to_xml")()

    def _to_xml_parse_format(self, parent_override = None, act_override=False):
        """
            Special section for DeviceFormat
        """
        # Determine parent
        if not act_override:
            parent_elem = self.format_elems
        else:
            parent_elem = self.desfmt_elems

        # Just a small tweak, count it
        tmp_count = parent_elem.attrib.get("Count")
        if tmp_count is not None:
            tmp_count = int(tmp_count) + 1
        else:
            tmp_count = 1

        parent_elem.set("Count", str(tmp_count))
        # Start adding elements to format section
        self.xml_elems_list.append(ET.SubElement(parent_elem,
                                                 self.tmp_full_name.split(".")[-1]))
        self.xml_elems_list[-1].set("type", self.tmp_full_name)
        self.xml_elems_list[-1].set("ObjectID", str(self.tmp_id))

        new_obj_init = getattr(self.xml_tmp_obj, "_to_xml_init")
        new_obj_init = new_obj_init(self.xml_root_elem,
                                    parent_override=parent_elem[-1],
                                    xml_done_ids=self.xml_done_ids,
                                    act_override=act_override)
        # Finally, start parsing
        getattr(self.xml_tmp_obj, "to_xml")()

################################################################################
########### Special occasion of sub-to_xml
    def _to_xml_parse_device(self, act_override=False):
        """
            Special section for any other device, that is not in blivet.devices
        """
        # Get basic data and ID
        self.xml_tmp_id = getattr(self.xml_tmp_obj, "id")
        if self.xml_tmp_id in self.xml_done_ids:
            return

        if not act_override:
            parent_elem = self.intern_elems
        else:
            parent_elem = self.desdev_elems

        # Just a small tweak, count it
        tmp_count = parent_elem.attrib.get("Count")
        if tmp_count is not None:
            tmp_count = int(tmp_count) + 1
        else:
            tmp_count = 1
        parent_elem.set("Count", str(tmp_count))
        # Finally, start preparing
        self.xml_done_ids.add(self.xml_tmp_id)
        self.xml_elems_list.append(ET.SubElement(parent_elem, self.xml_tmp_str_type.split(".")[-1]))
        self.xml_elems_list[-1].set("type", self.xml_tmp_str_type)
        self.xml_elems_list[-1].set("ObjectID", str(self.xml_tmp_id))

        new_obj_init = getattr(self.xml_tmp_obj, "_to_xml_init")
        new_obj_init = new_obj_init(self.xml_root_elem,
                                    parent_override=parent_elem[-1],
                                    object_override=self.xml_tmp_obj,
                                    devices_list=self.xml_devices_list,
                                    xml_done_ids=self.xml_done_ids,
                                    act_override=act_override)
        # Finally, start parsing
        getattr(self.xml_tmp_obj, "to_xml")()


################################################################################
##### Set data
    def _to_xml_get_data(self, in_attrib=None, in_obj=None):
        """ This basically gets the object.
        """
        # Decide if it is already completed object or not
        if in_obj is not None:
            self.xml_tmp_obj = in_obj
        else:
            self.xml_tmp_obj = getattr(self.xml_object, in_attrib)

        self.xml_tmp_type = type(self.xml_tmp_obj)
        self.xml_tmp_str_type = str(self.xml_tmp_type).split("'")[-2]

    def _to_xml_set_value(self, par_elem):
        """
            This just sets the data's value into element text.
            If obj_override is True, the object is re-assigned back.
        """
        # Set this, because we need it for re-assigning.
        tmp_obj = None
        # Special condition for size
        if "Size" in self.xml_tmp_str_type:
            par_elem.set("Size", str(self.xml_tmp_obj))
            self.xml_tmp_obj = int(self.xml_tmp_obj)
        # Object that has ID
        elif hasattr(self.xml_tmp_obj, "id"):
            tmp_obj = self.xml_tmp_obj
            self.xml_tmp_obj = getattr(self.xml_tmp_obj, "id")
        par_elem.text = str(self.xml_tmp_obj)

        # We dont want parted, give at least info that we processed it
        if "parted." in self.xml_tmp_str_type:
            par_elem.text = "NOT IMPLEMENTED %s" % (self.xml_tmp_str_type)

        # Dirty trick: re-assign object back
        tmp_id = self.xml_tmp_obj
        self.xml_tmp_obj = tmp_obj
        self.tmp_id = tmp_id

    def _to_xml_set_data_type(self, par_elem):
        """
            This just sets the data's type converted in string, nothing else.
        """
        # Does it have ID?
        if hasattr(self.xml_tmp_obj, "id"):
            self.xml_tmp_str_type = "ObjectID"
        # Finally, set the type
        if par_elem.attrib.get("type") is None:
            par_elem.set("type", self.xml_tmp_str_type)

################################################################################
##### Base element appending
    def _to_xml_base_elem(self, in_attrib):
        self.xml_elems_list.append(ET.SubElement(self.xml_parent_elem, "prop"))
        self.xml_elems_list[-1].set("attr", in_attrib)

################################################################################
##### EXPORT FUNCTION
    def to_xml(self):
        """
            This is the main function, that does the export.
            All of the above are subfunctions / methods, that are used by to_xml().
        """
        for attr in self.xml_attr_list:
            try:
                # Temporaily get str_type
                tmp_obj = getattr(self.xml_object, attr)
                self.xml_tmp_str_type = str(type(tmp_obj)).split("'")[-2]
                # Check, if it is allowed attrib or not
                if self._to_xml_check_igns(attr):
                    continue
                # Basic fix - replace all underscore attrs with non-underscore
                if attr.startswith("_") and hasattr(self.xml_object, attr[1:]):
                    attr = attr[1:]
                # Add to completed attributes, so we can avoid duplicates. Also add ids
                self.xml_attrs_done.add(attr)
                # Temporaily get object
                self._to_xml_get_data(attr)
                # Create basic element
                self._to_xml_base_elem(attr)
                # Set basic data to element
                self._to_xml_set_data_type(self.xml_elems_list[-1])

                # Anything that can be iterated
                if (self.xml_tmp_type in self.xml_iterables and self.xml_tmp_obj is not None) or\
                ("ParentList" in self.xml_tmp_str_type and self.xml_tmp_obj is not None):
                    self._to_xml_parse_iterables(self.xml_tmp_obj)

                elif hasattr(self.xml_tmp_obj, "to_xml"):
                    self._to_xml_parse_sub_to_xml()

                # Normal attribute
                else:
                    self._to_xml_set_value(self.xml_elems_list[-1])

            except Exception as e:
                check_issue = str(e)
                if "unreadable attribute" in check_issue or\
                    "can only be accessed" in check_issue:
                    continue
                #else:
                    #print (e, attr, self.xml_tmp_obj)
                    #print("TRACEBACK")
                    #traceback.print_tb(e.__traceback__)

    def _getdeepattr(self, obj, name):
        """This behaves as the standard getattr, but supports
           composite (containing dots) attribute names.

           As an example:

           >>> import os
           >>> from os.path import split
           >>> getdeepattr(os, "path.split") == split
           True
        """

        for attr in name.split("."):
            obj = getattr(obj, attr)
        return obj

    def _hasdeepattr(self, obj, name):
        """
            This behaves like getdeepattr, but returns a booolean if True or False if not.
            Implementation by kvalek@redhat.com, inspired by getdeepattr

            This is stand-alone version, original method version used in blivet/util.py, as part of to_xml() project.

            Example (done in ipython3)
            dap2._hasdeepattr(dap2, "parents.items")
            True
        """

        for attr in name.split("."):
            try:
                obj = getattr(obj, attr)
            except AttributeError:
                return False
        return True

################################################################################
####################### IMPORT FUNCTIONS #######################################
class FromXML(object):
    def __init__(self, xml_file, devicetree):
        """
            Basic initialization
        """
        super(FromXML, self).__init__()

        # Get master trees
        self.fxml_tree_root = ET.parse(xml_file).getroot()
        self.fxml_tree_devices = self.fxml_tree_root.find("./Devices")
        self.fxml_tree_formats = self.fxml_tree_root.find("./Formats")
        self.fxml_tree_interns = self.fxml_tree_root.find("./InternalDevices")
        self.fxml_tree_actions = self.fxml_tree_root.find("./Actions")
        # Lists to store devices to - Preparation

        # Pouzit ids_done jako kontrolu proti rekurzi
        self.ids_done = {}
        # Little optimalization: use dict to get object if its imported already
        self.fulltypes_stack = {}
        # Define devicetree / populator
        self.devicetree = devicetree
        # Post-processing dictionary
        self.post_process_list = []

################################################################################
####################### Iteration ##############################################
    def from_xml(self, in_list=None, ign_atts=None, postprocess_attrs=None):
        """
            Walks through tree_devices
        """
        # DEBUG:
        #self.fxml_tree_devices = [self.fxml_tree_devices[10]]
        #self.fxml_tree_devices = self.fxml_tree_interns
        if in_list is None:
            in_list = self.fxml_tree_devices

        for dev_elem in in_list:
            dev_id = dev_elem.attrib.get("ObjectID")
            if self.ids_done.get(dev_id) is not None:
                continue
            self.from_xml_internal(dev_elem, debug=False,
                                   ign_atts=ign_atts, postprocess_attrs=postprocess_attrs)

    def from_xml_internal(self, dev_elem, id_list=list(),
                          debug=False, ign_atts=None, postprocess_attrs=None):
        """
            This loop function basically creates all of the information - Gets
            class of the device and also it's ID and then processes all attributes
            that are tied to a device

            if param debug is True: processes a object and initializes it. else
            it just gives back the dev_dict
        """
        dev_str_type = dev_elem.attrib.get("type")
        dev_id = dev_elem.attrib.get("ObjectID")
        dev_dict = {"class": self._fxml_process_module(dev_str_type), "XMLID": dev_id}
        # We don't want these attributes to be processed, because they are processed automatically
        if ign_atts is None:
            ign_atts = {"children", "ancestors", "lvs", "thinpools", "thinlvs"}

        # TODO: dokoncit cached_lvs, _internal_lvs
        if postprocess_attrs is None:
            postprocess_attrs = {"cached_lvs", "_internal_lvs", "cached_lv"}

        # Append ID to control list so we can skip it if we'll find it somewhere else
        id_list.append(dev_id)

        for attr_elem in dev_elem:
            tmp_attr = attr_elem.attrib.get("attr")
            if tmp_attr in ign_atts:
                continue
            if tmp_attr in postprocess_attrs:
                self.post_process_list.append(FXMLPostProcess(tmp_attr, dev_elem, attr_elem, id_list[-1]))
                continue
            self._fxml_determine_type(attr_elem, in_dict=dev_dict, id_list=id_list)

        if not debug:
            del id_list[-1]
            return self._fxml_finalize_object(dev_dict)
        else:
            print (dev_dict)

    def from_xml_postprocess(self):
        """
            Based on stacked data, performs post-import processing to import and
            process data we were unable to process in normal import
        """
        self.from_xml(in_list=self.fxml_tree_interns, ign_atts={"ancestors", "parents", "_internal_lvs"})

        for dev_cls in self.post_process_list:
            elem = dev_cls.elem
            tmp_obj = self.ids_done.get(dev_cls.cur_id)
            if elem.attrib.get("type") == "list":
                tmp_value = []
                for attr_elem in elem:
                    tmp_value.append(self.ids_done.get(attr_elem.text))
            else:
                tmp_value = self.ids_done.get(elem.text)

            if dev_cls.tmp_attr == "cached_lvs":
                dev_cls.tmp_attr = "_cached_lvs"
            setattr(tmp_obj, dev_cls.tmp_attr, tmp_value)

################################################################################
####################### Tooling functions ######################################
    def _fxml_determine_type(self, in_elem, in_dict=None,
                             in_attr=None, id_list=None, debug=False):
        """
            This determines between basic simple type (iterables and simple) and
            complex, like attributes containing a dot and ObjectID, which we
            want to process separatelly.

            Note: in_dict is allowed to be passed just when beggining typing the
            attribute.

            in_elem is required, because we need to parse information from the
            element.

            Processing: if the in_dict is None, then it will return the value
            if not, value is directly written in in_dict[tmp_attr]

            If debug parameterer is False, all of the types are processed. If not,
            only complex attributes and objects are processed.
        """
        # Define basic types
        iterables = {"list", "dict", "tuple"}
        simples = {"str", "int", "float", "bool"}
        # Get tempovary type
        tmp_str_type = in_elem.attrib.get("type")
        tmp_attr = in_elem.attrib.get("attr")
        if tmp_attr is None:
            tmp_attr = in_attr

        # Any attribute that is a link to a object
        if tmp_str_type == "ObjectID" and in_elem.text not in id_list:
            if in_dict is None:
                return self._fxml_process_object(in_elem, id_list)
            in_dict[tmp_attr] = self._fxml_process_object(in_elem, id_list)
        # Any simple
        elif tmp_str_type in simples:
            if in_dict is None:
                return self._fxml_process_simple(in_elem)
            in_dict[tmp_attr] = self._fxml_process_simple(in_elem)
        # Any iterable
        elif tmp_str_type in iterables or "ParentList" in tmp_str_type:
            if in_dict is None:
                return self._fxml_process_iterables(in_elem, id_list)
            in_dict[tmp_attr] = self._fxml_process_iterables(in_elem, id_list)
        # Any complex
        elif "." in tmp_str_type and "ParentList" not in tmp_str_type:
            if in_dict is None:
                return self._fxml_determine_complex(in_elem)
            in_dict[tmp_attr] = self._fxml_determine_complex(in_elem)

    def _fxml_determine_complex(self, in_elem):
        """
            Determines, what type of complex object we are processing
        """
        tmp_str_type = in_elem.attrib.get("type")
        tmp_value = in_elem.text
        tmp_class = self._fxml_process_module(tmp_str_type)

        # Occasion for size
        if "Size" in tmp_str_type:
            return tmp_class(int(tmp_value))
        # Occasion for raid-s
        elif tmp_str_type.startswith("blivet.devicelibs.raid"):
            return tmp_value
        # Occasion for object that was re-typed on export
        elif in_elem.attrib.get("ObjectID") is not None:
            return self.from_xml_internal(in_elem)
        # return the class itself if everything fails
        else:
            return tmp_class

################################################################################
####################### Attribute processing functions #########################
    def _fxml_process_object(self, in_elem, id_list):
        """
            Processes object
        """
        process_id = in_elem.text
        tmp_element = self.fxml_tree_root.find(".//*[@ObjectID='%s']" % (process_id))
        # Check for devicetree, if it already exists so we can skip it
        dev_tree_name = tmp_element.find("./*[@attr='name']").text
        if self.devicetree.get_device_by_name(dev_tree_name) is not None:
            return self.devicetree.get_device_by_name(dev_tree_name)
        else:
            return self.from_xml_internal(tmp_element, id_list)

    def _fxml_process_module(self, tmp_str_type):
        """
            Reconstructs the class based on type
            Returns: class
        """
        # Try to get type, if it is already in types dictionary
        tmp_type = self.fulltypes_stack.get(tmp_str_type)
        if tmp_type is not None:
            return tmp_type
        else:
            # If it fails, create one
            tmp_imp_path = ""

            # Iterate through the "fulltype" and get all that is everyhing before
            # last dot. Also, make correct path
            for mod_str in range(len(tmp_str_type.split(".")) - 1):
                if tmp_imp_path == "":
                    tmp_imp_path = tmp_str_type.split(".")[0]
                else:
                    tmp_imp_path = tmp_imp_path + "." + tmp_str_type.split(".")[mod_str]
            # Create the class itself
            tmp_mod_name = tmp_str_type.split(".")[-1]
            # Create a tempovary object that we store later in fulltypes_stack
            tmp_class_obj = getattr(importlib.import_module(tmp_imp_path), tmp_mod_name)
            self.fulltypes_stack.update({tmp_str_type: tmp_class_obj})
            return tmp_class_obj

    def _fxml_process_simple(self, in_elem):
        """
            Processes simple values
        """
         # Define simple types and values
        simple_types = {"int": int, "float": float} # Note: str missing intentionally, parsed by default.
        simple_values = {"True": True, "False": False}
        # "unpack" the element
        tmp_str_type = in_elem.attrib.get("type")
        tmp_value = in_elem.text
        # First check type instances
        if simple_types.get(tmp_str_type) is not None:
            tmp_type = simple_types.get(tmp_str_type)
            tmp_value = tmp_type(tmp_value)
        elif "str" in tmp_str_type:
            # Special override for empty text
            if tmp_value is None:
                tmp_value = ""
            else:
                pass
        elif "." in tmp_str_type:
            tmp_value = in_elem.text
        else:
            tmp_value = simple_values.get(tmp_value)
        return tmp_value

    def _fxml_process_iterables(self, in_elem, id_list):
        """
            Any iterable type
        """
        # Define basics
        list_objects = {"list": list(), "dict": dict(), "set": set(), "tuple": list()}
        list_attribs = {"parents": list()}
        # Unpack element
        tmp_str_type = in_elem.attrib.get("type")
        tmp_attr = in_elem.attrib.get("attr")
        # Assign types
        list_object = list_objects.get(tmp_str_type)
        if list_object is None:
            list_object = list_attribs.get(tmp_attr)

        # Finally, start iterating
        for item_elem in in_elem: # Not to be confused, this element has children
            # Preliminary check for IDs
            if item_elem.attrib.get("ObjectID") is not None and item_elem.text in id_list:
                continue
            tmp_value = self._fxml_determine_type(item_elem, id_list=id_list, in_attr=tmp_attr)

            # Determine, which type of list to use
            if type(list_object) is list:
                list_object.append(tmp_value)
            elif type(list_object) is dict:
                lst_tmp_attr = item_elem.attrib.get("attr")
                list_object[lst_tmp_attr] = tmp_value
            elif type(list_object) is set:
                list_object.add(tmp_value)

        # Post-loop check for tuple
        if tmp_str_type == "tuple":
            tmp_value = tuple(list_object)
        return list_object

    def _fxml_process_object(self, in_elem, id_list):
        """
            Processes object
        """
        process_id = in_elem.text
        tmp_element = self.fxml_tree_root.find(".//*[@ObjectID='%s']" % (process_id))
        if self.ids_done.get(process_id) is not None:
            return self.ids_done.get(process_id)
        else:
            return self.from_xml_internal(tmp_element, id_list=id_list)

################################################################################
########## Object finalization #################################################
    def _fxml_finalize_object(self, in_dict):
        """
            Completes and initalizes object based on dictionary provided
        """
        # First, get all basic data
        tmp_class = in_dict.get("class")
        tmp_id = in_dict.get("XMLID")
        # Init the object
        tmp_obj = tmp_class.__init_xml__(in_dict)
        result = self.fxml_tree_root.find(".//*[@ObjectID='%s']/.." % (tmp_id)).tag

        # Define LVMCache
        LVMCache = getattr(importlib.import_module("blivet.devices.lvm"), "LVMCache")

        if self.ids_done.get(tmp_id) is None:
            self.ids_done[tmp_id] = tmp_obj
        if isinstance(tmp_obj, LVMCache):
            return tmp_obj
        elif result == "Devices" and tmp_obj not in self.devicetree.devices:
            self.devicetree._add_device(tmp_obj)
        return tmp_obj

################################################################################
########## Helper postprocessing class #########################################
class FXMLPostProcess(object):
    """
        Defines a simple class to assist postprocess
    """
    def __init__(self, attr, dev_elem, cur_elem, in_id):
        super(FXMLPostProcess, self).__init__()
        self.tmp_attr = attr
        self.cur_id = in_id
        self.elem = cur_elem
        self.dev_elem = dev_elem
        self.tmp_id = dev_elem.attrib.get("ObjectID")
