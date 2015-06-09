import unittest

import blivet.tasks.task as task
import blivet.tasks.availability as availability

class BasicUnavailableApplication(task.BasicApplication):
    ext = availability.unavailable_resource("unavailable")
    description = "unavailable application"

    def doTask(self):
        pass

class BasicAvailableApplication(task.BasicApplication):
    ext = availability.available_resource("available")
    description = "available application"

    def doTask(self):
        pass

class ResourceTestCase(unittest.TestCase):

    def testAvailabililty(self):
        unavailable_resource = availability.unavailable_resource("unavailable")
        self.assertNotEqual(unavailable_resource.availabilityErrors, [])
        self.assertFalse(unavailable_resource.available)

        available_resource = availability.available_resource("available")
        self.assertEqual(available_resource.availabilityErrors, [])
        self.assertTrue(available_resource.available)

class TasksTestCase(unittest.TestCase):

    def testAvailability(self):
        unavailable_app = BasicUnavailableApplication()
        self.assertFalse(unavailable_app.available)
        self.assertNotEqual(unavailable_app.availabilityErrors, [])

        available_app = BasicAvailableApplication()
        self.assertTrue(available_app.available)
        self.assertEqual(available_app.availabilityErrors, [])

    def testNames(self):
        # Every basic application takes its string representation from
        # the external resource.
        unavailable_app = BasicUnavailableApplication()
        self.assertTrue(isinstance(unavailable_app, task.BasicApplication))
        self.assertEqual(str(unavailable_app), str(unavailable_app.ext))
