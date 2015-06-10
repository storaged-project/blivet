import six
from unittest import TestCase

# deprecation compatibility b/w python 2 and 3
if six.PY2:
    TestCase.assertRaisesRegex = TestCase.assertRaisesRegexp
    TestCase.assertRegex = TestCase.assertRegexpMatches

