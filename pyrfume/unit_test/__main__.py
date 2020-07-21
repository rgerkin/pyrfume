import sys
import unittest

from .test_config_data import *
from .test_make_solutions import *
from .test_mixture import *
from .test_test import *

def main():
    buffer = 'buffer' in sys.argv
    sys.argv = sys.argv[:1] # :Args need to be removed for __main__ to work.  
    unittest.main(buffer=buffer)

if __name__ == '__main__':
    main()
