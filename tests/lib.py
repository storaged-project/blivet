
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
        for lm in leftmissing:
            s += " %s\n" % (pprint.pformat(lm),)

    if rightmissing:
        s += "expected: \n"
        for rm in rightmissing:
            s += " %s\n" % (pprint.pformat(rm),)

    if leftmissing or rightmissing:
        raise AssertionError(s)


def assertVerboseEqual(left, right, msg=None):
    if left != right:
        ll = len(left)
        rl = len(right)
        for x in range(0, max(ll, rl)):
            if x > ll - 1:
                assertVerboseEqual(None, right[x], msg)
            if x > rl - 1:
                assertVerboseEqual(left[x], None, msg)
            if left[x] != right[x]:
                if msg:
                    raise AssertionError(msg)
                else:
                    raise AssertionError("%s != %s" % (
                        pprint.pformat(left), pprint.pformat(right)))
