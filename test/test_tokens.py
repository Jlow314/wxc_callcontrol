from unittest import TestCase
from base import TestCaseWithTokens


class Test(TestCaseWithTokens):

    def test_get_tokens(self):
        print(self.tokens)
