
import pprint


def assertVerboseListEqual(left, right, msg=None):
    left.sort()
    right.sort()

    found = []
    rightmissing = []
    leftmissing = []
    for x in left:
        if x in right:
            found.append(x)
        else:
            rightmissing.append(x)
    for x in right:
        if x not in found:
            leftmissing.append(x)
    if msg:
        raise AssertionError(msg)

    s = "\n"
    if leftmissing:
        s += "log has: \n"
        for l in leftmissing:
            s += " %s\n" % (pprint.pformat(l),)

    if rightmissing:
        s += "expected: \n"
        for r in rightmissing:
            s += " %s\n" % (pprint.pformat(r),)

    if leftmissing or rightmissing:
        raise AssertionError(s)


def assertVerboseEqual(left, right, msg=None):
    if left != right:
        l = len(left)
        r = len(right)
        for x in range(0, max(l, r)):
            if x > l - 1:
                assertVerboseEqual(None, right[x], msg)
            if x > r - 1:
                assertVerboseEqual(left[x], None, msg)
            if left[x] != right[x]:
                if msg:
                    raise AssertionError(msg)
                else:
                    raise AssertionError("%s != %s" % (
                        pprint.pformat(left), pprint.pformat(right)))
