"""remainderbot: spend expiring subscription quota on one finished unit of work."""
import sys

# here, before any module imports tomllib (3.11+): an older Python gets this line, not a traceback
if sys.version_info < (3, 11):
    sys.exit("remainderbot needs Python 3.11 or newer; this is " + sys.version.split()[0])
