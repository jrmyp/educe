"""
Feature extraction library functions for RST_DT corpus
"""

from collections import namedtuple
from functools import wraps
import copy
import itertools
import os
import re
import sys

import educe.util
from educe.rst_dt import SimpleRSTTree, deptree, id_to_path
from educe.learning.csv import tune_for_csv
from educe.learning.keys import\
    ClassKeyGroup, KeyGroup, MergedKeyGroup,\
    MagicKey

if sys.version > '3':
    def treenode(tree):
        "API-change padding for NLTK 2 vs NLTK 3 trees"
        return tree.label()
else:
    def treenode(tree):
        "API-change padding for NLTK 2 vs NLTK 3 trees"
        return tree.node

# ---------------------------------------------------------------------
# feature extraction
# ---------------------------------------------------------------------

# The comments on these named tuples can be docstrings in Python3,
# or we can wrap the class, but eh...

# Global resources and settings used to extract feature vectors
FeatureInput = namedtuple('FeatureInput',
                          ['corpus', 'debug'])

# A document and relevant contextual information
DocumentPlus = namedtuple('DocumentPlus',
                          ['key', 'rsttree', 'deptree'])

# ---------------------------------------------------------------------
# single EDUs
# ---------------------------------------------------------------------


def edu_feature(wrapped):
    """
    Lift a function from `edu -> feature` to
    `single_function_input -> feature`
    """
    @wraps(wrapped)
    def inner(_, edu):
        "drops the context"
        return wrapped(edu)
    return inner


def edu_pair_feature(wrapped):
    """
    Lifts a function from `(edu, edu) -> f` to
    `pair_function_input -> f`
    """
    @wraps(wrapped)
    def inner(_, edu1, edu2):
        "drops the context"
        return wrapped(edu1, edu2)
    return inner


def clean_edu_text(text):
    """
    Strip metadata from EDU text
    """
    clean_text = text
    clean_text = re.sub(r'(\.|<P>|,)*$', r'', clean_text)
    clean_text = re.sub(r'^"', r'', clean_text)
    return clean_text


def clean_corpus_word(word):
    """
    Given a word from the corpus, return a slightly normalised
    version of that word
    """
    return word.lower()


def tokens_feature(wrapped):
    """
    Lift a function from `tokens -> feature` to
    `single_function_input -> feature`
    """
    @edu_feature
    @wraps(wrapped)
    def inner(edu):
        "(edu -> f) -> ((context, edu) -> f)"
        tokens = list(map(clean_corpus_word,
                          clean_edu_text(edu.text).split()))
        return wrapped(tokens)
    return inner

# ---------------------------------------------------------------------
# single EDU features
# ---------------------------------------------------------------------


@edu_feature
def feat_start(edu):
    "text span start"
    return edu.text_span().char_start


@edu_feature
def feat_end(edu):
    "text span end"
    return edu.text_span().char_end


@edu_feature
def feat_id(edu):
    "some sort of unique identifier for the EDU"
    return edu.identifier()


@tokens_feature
def word_first(tokens):
    "first word in the EDU (normalised)"
    return tokens[0] if tokens else None


@tokens_feature
def word_last(tokens):
    "last word in the EDU (normalised)"
    return tokens[-1] if tokens else None


@tokens_feature
def num_tokens(tokens):
    "number of distinct tokens in EDU text"
    return len(tokens)

# ---------------------------------------------------------------------
# pair EDU features
# ---------------------------------------------------------------------


@edu_pair_feature
def num_edus_between(edu1, edu2):
    "number of EDUs between the two EDUs"
    return abs(edu2.num - edu1.num) - 1

def feat_grouping(current, edu1, edu2):
    "which file in the corpus this pair appears in"
    return os.path.basename(id_to_path(current.key))


# ---------------------------------------------------------------------
# single EDU key groups
# ---------------------------------------------------------------------


class SingleEduSubgroup(KeyGroup):
    """
    Abstract keygroup for subgroups of the merged SingleEduKeys.
    We use these subgroup classes to help provide modularity, to
    capture the idea that the bits of code that define a set of
    related feature vector keys should go with the bits of code
    that also fill them out
    """
    def __init__(self, description, keys):
        super(SingleEduSubgroup, self).__init__(description, keys)

    def fill(self, current, edu, target=None):
        """
        Fill out a vector's features (if the vector is None, then we
        just fill out this group; but in the case of a merged key
        group, you may find it desirable to fill out the merged
        group instead)

        This defaults to _magic_fill if you don't implement it.
        """
        self._magic_fill(current, edu, target)

    def _magic_fill(self, current, edu, target=None):
        """
        Possible fill implementation that works on the basis of
        features defined wholly as magic keys
        """
        vec = self if target is None else target
        for key in self.keys:
            vec[key.name] = key.function(current, edu)


class SingleEduSubgroup_Meta(SingleEduSubgroup):
    """
    Basic EDU-identification features
    """

    _features =\
        [MagicKey.meta_fn(feat_id),
         MagicKey.meta_fn(feat_start),
         MagicKey.meta_fn(feat_end)]

    def __init__(self):
        desc = self.__doc__.strip()
        super(SingleEduSubgroup_Meta, self).__init__(desc, self._features)


class SingleEduSubgroup_Text(SingleEduSubgroup):
    """
    Properties of the EDU text itself
    """
    _features =\
        [MagicKey.discrete_fn(word_first),
         MagicKey.discrete_fn(word_last),
         MagicKey.continuous_fn(num_tokens)]

    def __init__(self):
        desc = self.__doc__.strip()
        super(SingleEduSubgroup_Text, self).__init__(desc, self._features)


class SingleEduKeys(MergedKeyGroup):
    """
    single EDU features
    """
    def __init__(self, inputs):
        groups = [SingleEduSubgroup_Meta(),
                  SingleEduSubgroup_Text()]
        #if inputs.debug:
        #    groups.append(SingleEduSubgroup_Debug())
        desc = self.__doc__.strip()
        super(SingleEduKeys, self).__init__(desc, groups)

    def fill(self, current, edu, target=None):
        """
        See `SingleEduSubgroup.fill`
        """
        vec = self if target is None else target
        for group in self.groups:
            group.fill(current, edu, vec)


# ---------------------------------------------------------------------
# EDU pairs
# ---------------------------------------------------------------------


class PairSubgroup(KeyGroup):
    """
    Abstract keygroup for subgroups of the merged PairKeys.
    We use these subgroup classes to help provide modularity, to
    capture the idea that the bits of code that define a set of
    related feature vector keys should go with the bits of code
    that also fill them out
    """
    def __init__(self, description, keys):
        super(PairSubgroup, self).__init__(description, keys)

    def fill(self, current, edu1, edu2, target=None):
        """
        Fill out a vector's features (if the vector is None, then we
        just fill out this group; but in the case of a merged key
        group, you may find it desirable to fill out the merged
        group instead)

        Defaults to _magic_fill if not defined
        """
        self._magic_fill(current, edu1, edu2, target)

    def _magic_fill(self, current, edu1, edu2, target=None):
        """
        Possible fill implementation that works on the basis of
        features defined wholly as magic keys
        """
        vec = self if target is None else target
        for key in self.keys:
            vec[key.name] = key.function(current, edu1, edu2)


class PairSubGroup_Core(PairSubgroup):
    "core features"

    def __init__(self):
        desc = self.__doc__.strip()
        keys =\
            [MagicKey.meta_fn(feat_grouping)]
        super(PairSubGroup_Core, self).__init__(desc, keys)


class PairSubgroup_Gap(PairSubgroup):
    """
    Features related to the combined surrounding context of the
    two EDUs
    """

    def __init__(self):
        desc = "the gap between EDUs"
        keys =\
            [MagicKey.continuous_fn(num_edus_between)]
        super(PairSubgroup_Gap, self).__init__(desc, keys)


class PairKeys(MergedKeyGroup):
    """
    pair features

    sf_cache should only be None if you're just using this
    to generate help text
    """
    def __init__(self, inputs, sf_cache=None):
        """
        """
        self.sf_cache = sf_cache
        groups = [PairSubGroup_Core(),
                  PairSubgroup_Gap()]
        #          PairSubgroup_Tuple(inputs, sf_cache)]
        #if inputs.debug:
        #    groups.append(PairSubgroup_Debug())

        if sf_cache is None:
            self.edu1 = SingleEduKeys(inputs)
            self.edu2 = SingleEduKeys(inputs)
        else:
            self.edu1 = None  # will be filled out later
            self.edu2 = None  # from the feature cache

        desc = "pair features"
        super(PairKeys, self).__init__(desc, groups)

    def csv_headers(self):
        return super(PairKeys, self).csv_headers() +\
            [h + "_EDU1" for h in self.edu1.csv_headers()] +\
            [h + "_EDU2" for h in self.edu2.csv_headers()]

    def csv_values(self):
        return super(PairKeys, self).csv_values() +\
            self.edu1.csv_values() +\
            self.edu2.csv_values()

    def help_text(self):
        lines = [super(PairKeys, self).help_text(),
                 "",
                 self.edu1.help_text()]
        return "\n".join(lines)

    def fill(self, current, edu1, edu2, target=None):
        "See `PairSubgroup`"
        vec = self if target is None else target
        vec.edu1 = self.sf_cache[edu1]
        vec.edu2 = self.sf_cache[edu2]
        for group in self.groups:
            group.fill(current, edu1, edu2, vec)

# ---------------------------------------------------------------------
# extraction generators
# ---------------------------------------------------------------------


def simplify_deptree(dtree):
    """
    Boil a dependency tree down into a dictionary from (edu, edu) to rel
    """
    relations = {}
    for subtree in dtree:
        src = treenode(subtree).edu
        for child in subtree:
            cnode = treenode(child)
            relations[(src, cnode.edu)] = cnode.rel
    return relations


def preprocess(inputs, k):
    """
    Pre-process and bundle up a representation of the current document
    """
    rtree = SimpleRSTTree.from_rst_tree(inputs.corpus[k])
    dtree = deptree.relaxed_nuclearity_to_deptree(rtree)
    return DocumentPlus(k, rtree, dtree)


def extract_pair_features(inputs, live=False):
    """
    Return a pair of dictionaries, one for attachments
    and one for relations
    """
    for k in inputs.corpus:
        current = preprocess(inputs, k)
        edus = current.rsttree.leaves()
        # reduced dependency graph as dictionary (edu to [edu])
        relations = simplify_deptree(current.deptree) if not live else {}

        # single edu features
        sf_cache = {}
        for edu in edus:
            sf_cache[edu] = SingleEduKeys(inputs)
            sf_cache[edu].fill(current, edu)

        for epair in itertools.product(edus, edus):
            edu1, edu2 = epair
            if edu1 == edu2:
                continue
            vec = PairKeys(inputs, sf_cache=sf_cache)
            vec.fill(current, edu1, edu2)

            if live:
                yield vec, vec
            else:
                pairs_vec = ClassKeyGroup(vec)
                rels_vec = ClassKeyGroup(vec)
                rels_vec.set_class(relations[epair] if epair in relations
                                   else 'UNRELATED')
                pairs_vec.set_class(epair in relations)

            yield pairs_vec, rels_vec


# ---------------------------------------------------------------------
# input readers
# ---------------------------------------------------------------------


def read_common_inputs(args, corpus):
    """
    Read the data that is common to live/corpus mode.
    """
    return FeatureInput(corpus, args.debug)


def read_help_inputs(_):
    """
    Read the data (if any) that is needed just to produce
    the help text
    """
    return FeatureInput(None, True)


def read_corpus_inputs(args):
    """
    Read the data (if any) that is needed just to produce
    training data
    """
    is_interesting = educe.util.mk_is_interesting(args)
    reader = educe.rst_dt.Reader(args.corpus)
    anno_files = reader.filter(reader.files(), is_interesting)
    corpus = reader.slurp(anno_files, verbose=True)
    return read_common_inputs(args, corpus)