
import unittest
import blivet.tsort


class TopologicalSortTestCase(unittest.TestCase):

    def run_test(self):
        items = [1, 2, 3, 4, 5]
        edges = [(5, 4), (4, 3), (3, 2), (2, 1)]
        graph = blivet.tsort.create_graph(items, edges)
        self._tsort_test(graph)

        edges = [(5, 4), (2, 3), (1, 5)]
        graph = blivet.tsort.create_graph(items, edges)
        self._tsort_test(graph)

        edges = [(5, 4), (4, 3), (3, 2), (2, 1), (3, 5)]
        graph = blivet.tsort.create_graph(items, edges)
        with self.assertRaises(blivet.tsort.CyclicGraphError):
            blivet.tsort.tsort(graph)

        edges = [(5, 4), (4, 3), (3, 2), (2, 1), (2, 3)]
        graph = blivet.tsort.create_graph(items, edges)
        with self.assertRaises(blivet.tsort.CyclicGraphError):
            blivet.tsort.tsort(graph)

        items = ['a', 'b', 'c', 'd']
        edges = [('a', 'c'), ('c', 'b')]
        graph = blivet.tsort.create_graph(items, edges)
        self._tsort_test(graph)

    def _tsort_test(self, graph):
        def check_order(order, graph):
            # since multiple solutions can potentially exist, just verify
            # that the ordering constraints are satisfied
            for parent, child in graph['edges']:
                if order.index(parent) > order.index(child):
                    return False
            return True

        try:
            order = blivet.tsort.tsort(graph)
        except Exception as e:  # pylint: disable=broad-except
            self.fail(e)

        # verify output list is of the correct length
        self.assertFalse(len(order) != len(graph['items']),
                         "sorted list length is incorrect")

        # verify that all ordering constraints are satisfied
        self.assertTrue(check_order(order, graph),
                        "ordering constraints not satisfied")
