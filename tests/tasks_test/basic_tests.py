import unittest

import blivet.tasks.task as task
import blivet.tasks.availability as availability


class BasicUnavailableApplication(task.BasicApplication):
    ext = availability.unavailable_resource("unavailable")
    description = "unavailable application"

    def do_task(self):  # pylint: disable=arguments-differ
        pass


class BasicAvailableApplication(task.BasicApplication):
    ext = availability.available_resource("available")
    description = "available application"

    def do_task(self):  # pylint: disable=arguments-differ
        pass


class ResourceTestCase(unittest.TestCase):

    def test_availabililty(self):
        unavailable_resource = availability.unavailable_resource("unavailable")
        self.assertNotEqual(unavailable_resource.availability_errors, [])
        self.assertFalse(unavailable_resource.available)

        available_resource = availability.available_resource("available")
        self.assertEqual(available_resource.availability_errors, [])
        self.assertTrue(available_resource.available)


class TasksTestCase(unittest.TestCase):

    def test_availability(self):
        unavailable_app = BasicUnavailableApplication()
        self.assertFalse(unavailable_app.available)
        self.assertNotEqual(unavailable_app.availability_errors, [])

        available_app = BasicAvailableApplication()
        self.assertTrue(available_app.available)
        self.assertEqual(available_app.availability_errors, [])

    def test_names(self):
        # Every basic application takes its string representation from
        # the external resource.
        unavailable_app = BasicUnavailableApplication()
        self.assertTrue(isinstance(unavailable_app, task.BasicApplication))
        self.assertEqual(str(unavailable_app), str(unavailable_app.ext))
