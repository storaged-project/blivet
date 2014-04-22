import inspect
import logging
import sys
import traceback

log = logging.getLogger("blivet")
log.addHandler(logging.NullHandler())

def function_name_and_depth():
    IGNORED_FUNCS = ["function_name_and_depth",
                     "log_method_call",
                     "log_method_return"]
    stack = inspect.stack()

    for i, frame in enumerate(stack):
        methodname = frame[3]
        if methodname not in IGNORED_FUNCS:
            return (methodname, len(stack) - i)

    return ("unknown function?", 0)

def log_method_call(d, *args, **kwargs):
    classname = d.__class__.__name__
    (methodname, depth) = function_name_and_depth()
    spaces = depth * ' '
    fmt = "%s%s.%s:"
    fmt_args = [spaces, classname, methodname]

    for arg in args:
        fmt += " %s ;"
        fmt_args.append(arg)

    for k, v in kwargs.items():
        fmt += " %s: %s ;"
        if "pass" in k.lower() and v:
            v = "Skipped"
        fmt_args.extend([k, v])

    log.debug(fmt, *fmt_args)

def log_method_return(d, retval):
    classname = d.__class__.__name__
    (methodname, depth) = function_name_and_depth()
    spaces = depth * ' '
    fmt = "%s%s.%s returned %s"
    fmt_args = (spaces, classname, methodname, retval)
    log.debug(fmt, *fmt_args)

def log_exception_info(log_func=log.debug, fmt_str=None, fmt_args=None):
    """Log detailed exception information.

       :param log_func: the desired logging function
       :param str fmt_str: a format string for any additional message
       :param fmt_args: arguments for the format string
       :type fmt_args: a list of str

       Note: the logging function indicates the severity level of
       this exception according to the calling function. log.debug,
       the default, is the lowest level.
    """
    fmt_args = fmt_args or []
    (_methodname, depth) = function_name_and_depth()
    spaces = depth * ' '
    log_func("%sCaught exception, continuing.", spaces)
    if fmt_str:
        fmt_str = "%sProblem description: " + fmt_str
        log_func(fmt_str, spaces, *fmt_args)
    log_func("%sBegin exception details.", spaces)
    tb = traceback.format_exception(*sys.exc_info())
    for line in (l.rstrip() for entry in tb for l in entry.split("\n") if l):
        log_func("%s    %s", spaces, line)
    log_func("%sEnd exception details.", spaces)
