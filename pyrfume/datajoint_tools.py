"""Convenience functions for working with DataJoint"""

import re
from importlib import import_module
from inspect import isclass

import datajoint as dj
dj.errors._switch_adapted_types(True)


def schematize(cls, schema: dj.schema):
    """Take a Python class and build a Datajoint table from it.

    Params:
        cls: The class to convert into a DataJoint table
        schema: The schema in which to add the table

    Returns:
        cls: The schematized class (now for use with DataJoint)
    """
    cls = type(cls.__name__, (dj.Manual, cls, object), {})
    cls = set_dj_definition(cls)
    cls = schema(cls)
    return cls


def set_dj_definition(cls, type_map: dict = None) -> None:
    """Set the definition property of a class by inspecting its attributes.

    Params:
        cls: The class whose definition attribute should be set
        type_map: Optional additional type mappings
    """
    # A mapping between python types and DataJoint types
    _type_map = {
        "int": "int", 
        "str": "varchar(256)", 
        "float": "float", 
        "datetime": "datetime", 
        "datetime.datetime": "datetime", 
        "bool": "tinyint"
    }
    # A list of python types which have no DataJoint
    # equivalent and so are unsupported
    unsupported = [list]
    if type_map:
        _type_map.update(type_map)
    dj_def = "%s_id: int auto_increment\n---\n" % cls.__name__.lower()
    cls_items = cls.__annotations__.items()
    for attr, type_hint in cls_items:
        if type_hint in unsupported:
            continue
        name = getattr(type_hint, "__name__", type_hint)
        default = getattr(cls, attr)
        if isinstance(default, dict):
            # Assume the class of objects in some_dict.keys() have corresponding tables in the database

            # For example, components: Dict[ClassA, int] = {a: 1, b: 2}
            # key_cls_name would be "ClassA"
            # part_cls_name would be "Component", 
            # note that the "s" at the end of the dict name will be removed.
            # 
            part_cls_name = attr[0].upper() + attr[1:]
            part_cls_name = part_cls_name[:-1] if part_cls_name[-1] == 's' else part_cls_name
            key_cls_name = type_hint.__args__[0].__forward_arg__ 
            
            part_cls = type(
                part_cls_name, 
                (dj.Part, object), 
                {
                    "definition": """
                    -> %s
                    -> %s
                    """ % (cls.__name__, key_cls_name)
                }
            )
            cls_dict = dict(vars(cls))
            cls_dict[part_cls_name] = part_cls
            cls = type(cls.__name__, tuple(cls.__bases__), {part_cls_name: part_cls})
            continue
        elif isinstance(default, str):
            default = '"%s"' % default
        elif isinstance(default, bool):
            default = int(default)
        elif default is None:
            default = "NULL"
        if name in _type_map:
            dj_def += "%s = %s : %s\n" % (attr, default, _type_map[name])
        else:
            dj_def += "-> %s\n" % name
    cls.definition = dj_def
    return cls


def import_classes(module_name: str, match: str = None) -> dict:
    """Import all classes from the named module'

    Params:
        module_name (str): Name of the module (e.g. 'pyrfume.odorants')
        match (str): Optional regex string for class names to match.

    Returns:
        dict: A dictionary of full class names and the classes themselves"""
    classes = {}
    # Import the module and iterate through its attributes
    module = import_module(module_name)
    for attr_name in dir(module):
        if match and not re.search(match, attr_name):
            continue
        attr = getattr(module, attr_name)
        if isclass(attr):
            # Add the class to this package's variables
            classes[attr_name] = attr
    return classes


# Demonstration of setting the definition.
# A demonstration of adding to the schema requires an active schema.
if __name__ == "__main__":

    class Stuff:
        """A regular Python class that does not use DataJoint.
        All of its attributes (that you want to use in DataJoint)
        must have type hints."""

        other: "OtherStuff" = None

        x: int = 3
        """type: int"""

        y: str = "something"
        """type: str"""

    # Set DataJoint definitions in each class based on inspection
    # of class attributes.
    set_dj_definition(Stuff)

    # Schematize each of these classes (will include foreign keys)
    from pyrfume.odorants import Molecule, Vendor, ChemicalOrder

    for cls in [Molecule, Vendor, ChemicalOrder]:
        locals()[cls.__name__] = djt.schematize(cls, schema)

    # May require a Jupyter notebook or other canvas
    dj.ERD(schema).draw()
