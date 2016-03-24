Test Suite Inheritance Diagram
------------------------------

Blivet's test suite relies on the base classes shown below. These classes
take care of working with fake block or loop devices.

.. inheritance-diagram::
    tests.imagebackedtestcase
    tests.loopbackedtestcase
    tests.storagetestcase
    tests.devicetree_test.BlivetResetTestCase

Actual test cases inherit either :class:`unittest.TestCase` or one of
these base classes. Some use cases require more levels of abstraction
which is shown on the following diagram.

.. inheritance-diagram::
    tests.devicetree_test
    tests.formats_test.fs_test
    tests.formats_test.fslabeling

Note: with :class:`sphinx.ext.inheritance_diagram` it is not possible to
generate an inheritance diagram of all available classes. The ones shown above
are considered a bit more important. If you want to see the inheritance diagram
for other classes add the following markup to this document and rebuild it::

    .. inheritance-diagram::
        tests.module_name.className
