"""
Porter Stemmer
==============

A vendored, public-domain implementation of the Porter stemming algorithm
(M.F. Porter, 1980). Used to collapse morphological variants so that
``authenticate`` / ``authentication`` / ``authenticating`` retrieve each other.

This is a faithful port of Vivake Gupta's public-domain Python implementation
(2001), lightly modernized. Pure stdlib — no dependencies — preserving the
client's zero-dependency guarantee.

Note: stemming fixes MORPHOLOGY (same root, different suffix). It does NOT fix
abbreviations (``auth`` vs ``authentication``) or synonyms (``login`` vs
``signin``) — those collapse via the optional semantic lane, not here.
"""


class _PorterStemmer:
    def __init__(self):
        self.b = ""   # buffer for word to be stemmed
        self.k = 0
        self.j = 0    # general offsets into the string

    def _cons(self, i: int) -> bool:
        """True if b[i] is a consonant."""
        ch = self.b[i]
        if ch in "aeiou":
            return False
        if ch == "y":
            return True if i == 0 else (not self._cons(i - 1))
        return True

    def _m(self) -> int:
        """Measure the number of consonant sequences between 0 and j."""
        n = 0
        i = 0
        while True:
            if i > self.j:
                return n
            if not self._cons(i):
                break
            i += 1
        i += 1
        while True:
            while True:
                if i > self.j:
                    return n
                if self._cons(i):
                    break
                i += 1
            i += 1
            n += 1
            while True:
                if i > self.j:
                    return n
                if not self._cons(i):
                    break
                i += 1
            i += 1

    def _vowelinstem(self) -> bool:
        """True if 0..j contains a vowel."""
        for i in range(self.j + 1):
            if not self._cons(i):
                return True
        return False

    def _doublec(self, j: int) -> bool:
        """True if j,j-1 are a double consonant."""
        if j < 1:
            return False
        if self.b[j] != self.b[j - 1]:
            return False
        return self._cons(j)

    def _cvc(self, i: int) -> bool:
        """True if i-2,i-1,i is consonant-vowel-consonant and the second c is
        not w, x or y (used to restore an -e)."""
        if i < 2 or not self._cons(i) or self._cons(i - 1) or not self._cons(i - 2):
            return False
        return self.b[i] not in "wxy"

    def _ends(self, s: str) -> bool:
        """True if 0..k ends with s; sets j."""
        length = len(s)
        if s[length - 1] != self.b[self.k]:
            return False
        if length > self.k + 1:
            return False
        if self.b[self.k - length + 1:self.k + 1] != s:
            return False
        self.j = self.k - length
        return True

    def _setto(self, s: str) -> None:
        """Set j+1..k to the string s, readjusting k."""
        length = len(s)
        self.b = self.b[:self.j + 1] + s + self.b[self.j + length + 1:]
        self.k = self.j + length

    def _r(self, s: str) -> None:
        if self._m() > 0:
            self._setto(s)

    def _step1ab(self) -> None:
        if self.b[self.k] == "s":
            if self._ends("sses"):
                self.k -= 2
            elif self._ends("ies"):
                self._setto("i")
            elif self.b[self.k - 1] != "s":
                self.k -= 1
        if self._ends("eed"):
            if self._m() > 0:
                self.k -= 1
        elif (self._ends("ed") or self._ends("ing")) and self._vowelinstem():
            self.k = self.j
            if self._ends("at"):
                self._setto("ate")
            elif self._ends("bl"):
                self._setto("ble")
            elif self._ends("iz"):
                self._setto("ize")
            elif self._doublec(self.k):
                self.k -= 1
                if self.b[self.k] in "lsz":
                    self.k += 1
            elif self._m() == 1 and self._cvc(self.k):
                self._setto("e")

    def _step1c(self) -> None:
        if self._ends("y") and self._vowelinstem():
            self.b = self.b[:self.k] + "i" + self.b[self.k + 1:]

    def _step2(self) -> None:
        if self.k <= 0:
            return
        ch = self.b[self.k - 1]
        if ch == "a":
            if self._ends("ational"):
                self._r("ate")
            elif self._ends("tional"):
                self._r("tion")
        elif ch == "c":
            if self._ends("enci"):
                self._r("ence")
            elif self._ends("anci"):
                self._r("ance")
        elif ch == "e":
            if self._ends("izer"):
                self._r("ize")
        elif ch == "l":
            if self._ends("bli"):
                self._r("ble")
            elif self._ends("alli"):
                self._r("al")
            elif self._ends("entli"):
                self._r("ent")
            elif self._ends("eli"):
                self._r("e")
            elif self._ends("ousli"):
                self._r("ous")
        elif ch == "o":
            if self._ends("ization"):
                self._r("ize")
            elif self._ends("ation"):
                self._r("ate")
            elif self._ends("ator"):
                self._r("ate")
        elif ch == "s":
            if self._ends("alism"):
                self._r("al")
            elif self._ends("iveness"):
                self._r("ive")
            elif self._ends("fulness"):
                self._r("ful")
            elif self._ends("ousness"):
                self._r("ous")
        elif ch == "t":
            if self._ends("aliti"):
                self._r("al")
            elif self._ends("iviti"):
                self._r("ive")
            elif self._ends("biliti"):
                self._r("ble")
        elif ch == "g":
            if self._ends("logi"):
                self._r("log")

    def _step3(self) -> None:
        ch = self.b[self.k]
        if ch == "e":
            if self._ends("icate"):
                self._r("ic")
            elif self._ends("ative"):
                self._r("")
            elif self._ends("alize"):
                self._r("al")
        elif ch == "i":
            if self._ends("iciti"):
                self._r("ic")
        elif ch == "l":
            if self._ends("ical"):
                self._r("ic")
            elif self._ends("ful"):
                self._r("")
        elif ch == "s":
            if self._ends("ness"):
                self._r("")

    def _step4(self) -> None:
        if self.k <= 0:
            return
        ch = self.b[self.k - 1]
        if ch == "a":
            if not self._ends("al"):
                return
        elif ch == "c":
            if not (self._ends("ance") or self._ends("ence")):
                return
        elif ch == "e":
            if not self._ends("er"):
                return
        elif ch == "i":
            if not self._ends("ic"):
                return
        elif ch == "l":
            if not (self._ends("able") or self._ends("ible")):
                return
        elif ch == "n":
            if not (self._ends("ant") or self._ends("ement")
                    or self._ends("ment") or self._ends("ent")):
                return
        elif ch == "o":
            if not ((self._ends("ion") and self.j >= 0
                     and self.b[self.j] in "st") or self._ends("ou")):
                return
        elif ch == "s":
            if not self._ends("ism"):
                return
        elif ch == "t":
            if not (self._ends("ate") or self._ends("iti")):
                return
        elif ch == "u":
            if not self._ends("ous"):
                return
        elif ch == "v":
            if not self._ends("ive"):
                return
        elif ch == "z":
            if not self._ends("ize"):
                return
        else:
            return
        if self._m() > 1:
            self.k = self.j

    def _step5(self) -> None:
        self.j = self.k
        if self.b[self.k] == "e":
            a = self._m()
            if a > 1 or (a == 1 and not self._cvc(self.k - 1)):
                self.k -= 1
        if self.b[self.k] == "l" and self._doublec(self.k) and self._m() > 1:
            self.k -= 1

    def stem(self, word: str) -> str:
        word = word.lower()
        if len(word) <= 2:
            return word
        self.b = word
        self.k = len(word) - 1
        self.j = 0
        self._step1ab()
        self._step1c()
        self._step2()
        self._step3()
        self._step4()
        self._step5()
        return self.b[:self.k + 1]


_STEMMER = _PorterStemmer()


def stem(word: str) -> str:
    """Return the Porter stem of a single (lowercased) word."""
    if not word:
        return word
    return _STEMMER.stem(word)
