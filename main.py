import colorama
from enum import Enum
import os
import re
import sys

#
# This is a tool to analyze dependencies within a codebase.
# This code does the absolute bare-minimum C parsing in order to understand include directives.
# No macros are expanded and no conditionals are evaluated.
# There are better and more optimal ways to implement this all, however, it does it's job! And it
# does it well (at least for small codebases). Not a whole lot of value in optimizing an
# inconsequential script.
#
# Includes will form a dependency graph (usually a DAG but not necessarily) and this graph is
# traversed depth-first. No include guards are evaluated but cycles are avoided.
#
# At the moment escape sequences in path-specs are not evaluated.
#
# The code also makes some assumptions about nomenclature. The code assumes YYY.c/cpp and YYY.h are
# part of the same node/unit/module. It also assumes that file/node/unit/module names are unique
# across directories. Furthermore it assumes the file extension of a file has only one segment.
#
# Copyright Jeremy Rifkin 2020-2024
#

def print_help():
    print("Ussage: python main.py <startfile> [search directories]")

Trigraph_translation_table = {
    "=": "#",
    "/": "\\",
    "'": "^",
    "(": "[",
    ")": "]",
    "!": "|",
    "<": "{",
    ">": "}",
    "-": "~"
}
def phase_one(string):
    # trigraphs
    i = 0
    translated_string = ""
    while i < len(string):
        if string[i] == "?" and i < len(string) - 2 and string[i + 1] == "?" and string[i + 2] in Trigraph_translation_table:
            translated_string += Trigraph_translation_table[string[i + 2]]
            i += 3
        else:
            translated_string += string[i]
            i += 1
    return translated_string

def phase_two(string):
    # backslash followed immediately by newline
    i = 0
    translated_string = ""
    # this is a really dirty way of taking care of line number errors for backslash + \n sequences
    line_debt = 0
    while i < len(string):
        if string[i] == "\\" and i < len(string) - 1 and string[i + 1] == "\n":
            i += 2
            line_debt += 1
        elif string[i] == "\n":
            translated_string += "\n" * (1 + line_debt)
            line_debt = 0
            i += 1
        else:
            translated_string += string[i]
            i += 1
    return translated_string

# lexer rules
lexer_rules = [
    "COMMENT", r"//.*(?=\n|$)",
    "MCOMMENT", r"/\*(?s:.)*\*/",
    "IDENTIFIER", r"[a-zA-Z_$][a-zA-Z0-9_$]*",
    "NUMBER", r"(?:0x|0b)?[0-9a-fA-F]+(?:.[0-9a-fA-F]+)?(?:[eEpP][0-9a-fA-F]+)?(?:u|U|l|L|ul|UL|ll|LL|ull|ULL|f|F)?",
    "STRING", r"\"(?P<STRING_CONTENT>(?:\\.|[^\"\\])*)\"",
    "CHAR", r"'(\\.|[^\'\\])'",
    "PREPROCESSING_DIRECTIVE", r"(?:#|%:)[a-z]+",
    "PUNCTUATION", r"[,.<>?/=;:~!#%^&*\-\+|\(\)\{\}\[\]]",
    "NEWLINE", r"\n",
    "WHITESPACE", r"[^\S\n]+" #r"\s+"
]
lexer_ignores = {"COMMENT", "MCOMMENT", "WHITESPACE"}
lexer_regex = ""
class Token:
    def __init__(self, token_type, value, line, pos):
        self.token_type = token_type
        self.value = value
        self.line = line
        self.pos = pos
        # only digraph that needs to be handled
        if token_type == "PREPROCESSING_DIRECTIVE":
            self.value = re.sub(r"^%:", "#", value)
        elif token_type == "NEWLINE":
            self.value = ""
    def __repr__(self):
        if self.value == "":
            return "{} {}".format(self.line, self.token_type)
        else:
            return "{} {} {}".format(self.line, self.token_type, self.value)
def init_lexer():
    global lexer_regex
    for i in range(0, len(lexer_rules), 2):
        name = lexer_rules[i]
        pattern = lexer_rules[i + 1]
        lexer_regex += ("" if lexer_regex == "" else "|") + "(?P<{}>{})".format(name, pattern)
    lexer_regex = re.compile(lexer_regex)

def phase_three(string):
    # tokenization
    tokens = []
    i = 0
    line = 1
    while True:
        if i >= len(string):
            break
        m = lexer_regex.match(string, i)
        if m:
            groupname = m.lastgroup
            if groupname not in lexer_ignores:
                if groupname == "STRING":
                    tokens.append(Token(groupname, m.group("STRING_CONTENT"), line, i))
                else:
                    tokens.append(Token(groupname, m.group(groupname), line, i))
            if groupname == "NEWLINE":
                line += 1
            if groupname == "MCOMMENT":
                line += m.group(groupname).count("\n")
            i = m.end()
        else:
            print(string)
            print(i)
            print(tokens)
            print(line)
            print("\n\n{}\n\n".format(string[i-5:i+20]))
            raise Exception("lexer error")
    # TODO ensure there's always a newline token at the end?
    return tokens

def peek_tokens(tokens, seq):
    if len(tokens) < len(seq):
        return False
    for i, token in enumerate(seq):
        if type(seq[i]) is tuple:
            if not (tokens[i].token_type == seq[i][0] and tokens[i].value == seq[i][1]):
                return False
        elif tokens[i].token_type != seq[i]:
            return False
    return True

def expect(tokens, seq, line, after, expected=None):
    good = True
    if len(tokens) < len(seq):
        good = False
    else:
        for i, token in enumerate(seq):
            if type(seq[i]) is tuple:
                if not (tokens[i].token_type == seq[i][0] and tokens[i].value == seq[i][1]):
                    good = False
                    break
            elif tokens[i].token_type != seq[i]:
                good = False
                break
    if not good:
        if expected is not None:
            raise Exception("parse error: expected {} after {} on line {}, found [{}, ...]".format(expected, after, line, tokens[0]))
        else:
            raise Exception("parse error: unexpected tokens following {} on line {}".format(after, line))

class Processor:
    def __init__(self, file_path):
        base = os.path.dirname(file_path)
        self.all_files = set()
        for root, dirs, files in os.walk(base):
            for f in files:
                if os.path.splitext(f)[1] in {".c", ".cpp", ".h", ".hpp"}:
                    self.all_files.add(f)
        self.visited = set()
        self.nodes = {}
        self.process_file(file_path)
        N = len(self.nodes)
        self.matrix = [[0 for _ in range(N)] for _ in range(N)]
        for key in self.nodes:
            node = self.nodes[key]
            row = node["i"]
            for d in node["dependencies"]:
                self.matrix[row][self.nodes[d]["i"]] = 1
        # deep copy
        self.matrix_closure = [[col for col in row] for row in self.matrix]
        G = self.matrix_closure
        # floyd-warshall
        for k in range(N):
            for i in range(N):
                for j in range(N):
                    G[i][j] = G[i][j] or (G[i][k] and G[k][j])
    @staticmethod
    def queue_all(queue, file_path):
        filename = os.path.splitext(file_path)[0]
        for ext in [".h", ".hpp", ".c", ".cpp"]:
            path = filename + ext
            if os.path.exists(path):
                queue.append(path)
    def process_file(self, file_path):
        file_name = os.path.basename(file_path)
        file_basename = os.path.splitext(os.path.basename(file_path))[0]
        directory = os.path.dirname(file_path)
        if file_name in self.visited:
            return
        self.visited.add(file_name)
        if file_basename not in self.nodes:
            self.nodes[file_basename] = {
                "i": len(self.nodes),
                "dependencies": set()
            }
        print("=" * 10, file_name, "=" * 10)
        #
        # There are better ways to do the input processing that would allow looping though the input only
        # once and not using extra memory, but it won't make enough of a performance difference to warrant.
        # At least for now.
        #
        # All that's needed is understanding #include directives in a file. In order to do that, only
        # primitive and bare-minimum tokenization is required.
        #

        # get file contents
        content = None
        with open(file_path, "r") as f:
            content = f.read()
        # trigraphs
        content = phase_one(content)
        # backslash newline
        content = phase_two(content)
        # tokenize
        tokens = phase_three(content)
        # process the file
        # Preprocessor directives are only valid if they are at the beginning of a line. Code makes
        # sure the next token is always at the start of the line going into each loop iteration.
        process_queue = [] # files queued up to process so that logic doesn't get put in the middle of the parse logic
        while len(tokens) > 0:
            token = tokens.pop(0)
            if token.token_type == "PREPROCESSING_DIRECTIVE" and token.value == "#include":
                line = token.line
                if len(tokens) == 0:
                    raise Exception("parse error: expected token following #include directive, found nothing")
                elif peek_tokens(tokens, ("STRING", )):
                    path_token = tokens.pop(0)
                    expect(tokens, ("NEWLINE", ), line, "#include declaration")
                    tokens.pop(0) # pop eol
                    print("{} #include \"{}\"".format(line, path_token.value))
                    #process_queue.append(path_token.value)
                    self.queue_all(process_queue, os.path.join(os.path.dirname(file_path), path_token.value))
                elif peek_tokens(tokens, (("PUNCTUATION", "<"), )):
                    # because tokens can get weird between the angle brackets, the path is extracted from the raw source
                    open_bracket = tokens.pop(0)
                    i = open_bracket.pos + 1
                    while True:
                        if i >= len(content):
                            # error unexpected eof
                            raise Exception("parse error: unexpected end of file in #include directive on line {}.".format(line))
                        if content[i] == ">":
                            # this is our exit condition
                            break
                        elif content[i] == "\n":
                            # unexpected newline
                            # don't know if this is technically allowed or not
                            raise Exception("parse error: unexpected newline in #include directive on line {}.".format(line))
                        i += 1
                    # extract path substring
                    path = content[open_bracket.pos + 1 : i]
                    # consume tokens up to the closing ">"
                    while True:
                        if len(tokens) == 0:
                            # shouldn't happen
                            raise Exception("internal parse error: unexpected eof")
                        token = tokens.pop(0)
                        if token.token_type == "PUNCTUATION" and token.value == ">":
                            # exit condition
                            break
                        elif token.token_type == "NEWLINE":
                            # shouldn't happen
                            raise Exception("internal parse error: unexpected newline")
                    expect(tokens, ("NEWLINE", ), line, "#include declaration")
                    tokens.pop(0) # pop eol
                    # library includes won't be traversed
                    print("{} #include <{}>".format(line, path))
                else:
                    raise Exception("parse error: unexpected token sequence after #include directive on line {}. This may be a valid preprocessing directive and reflect a shortcoming of this parser.".format(line))
            else:
                # need to consume the whole line of tokens
                while token.token_type != "NEWLINE" and len(tokens) > 0:
                    token = tokens.pop(0)
        # process the files d-f
        for include in process_queue:
            self.process_file(include)
            include_component = os.path.splitext(os.path.basename(include))[0]
            if include_component == file_basename:
                # can happen if yyy.c includes yyy.h
                continue
            self.nodes[file_basename]["dependencies"].add(include_component)

def print_header(matrix, labels):
    print(" " * 20, end="")
    for i in range(len(matrix)):
        print(" {}".format(labels[i][0]), end="")
    print()

def print_matrix(matrix, labels):
    for i, row in enumerate(matrix):
        print("{:>20} ".format(labels[i]), end="")
        for j, n in enumerate(row):
            if i == j:
                print("{}{}{} ".format(colorama.Fore.BLUE, "#" if n else "~", colorama.Style.RESET_ALL), end="")
            else:
                print("{} ".format("#" if n else "~"), end="")
        print()
    print()

def print_graphviz(p, labels):
    print("digraph G {")
    #print("\tnodesep=0.3;")
    #print("\tranksep=0.2;")
    #print("\tnode [shape=circle, fixedsize=true];")
    #print("\tedge [arrowsize=0.8];")
    #print("\tlayout=fdp;")

    print("\tsubgraph cluster_{} {{".format("direct"))
    print("\t\tlabel=\"{}\";".format("direct dependencies"))
    for i in range(len(labels)):
        print("\t\tn{} [label=\"{}\"];".format(i, labels[i]))
    print("\t\t", end="")
    for i, row in enumerate(p.matrix):
        for j, v in enumerate(row):
            if v:
                print("n{}->n{};".format(i, j), end="")
    print()
    print("\t}")

    offset = len(labels)
    print("\tsubgraph cluster_{} {{".format("indirect"))
    print("\t\tlabel=\"{}\";".format("dependency transitive closure"))
    for i in range(len(labels)):
        print("\t\tn{} [label=\"{}\"];".format(i + offset, labels[i]))
    print("\t\t", end="")
    for i, row in enumerate(p.matrix_closure):
        for j, v in enumerate(row):
            if v:
                print("n{}->n{}[color={}];".format(i + offset, j + offset, "black" if p.matrix[i][j] else "orange"), end="")
    print()
    print("\t}")
    print("}")

def main():
    # <startfile> [search directories]
    argv = sys.argv
    if len(argv) == 1:
        print_help()
        return
    if argv[1] == "-h" or argv[1] == "--help":
        print_help()
        return
    root = argv[1]
    path = argv[2:]

    init_lexer()
    p = Processor(root)

    # this is mainly for dev/debugging; make sure no components are missed in traversal
    #print("visited: ", p.visited)
    #print("all: ", p.all_files)
    print("xor: ", p.all_files ^ p.visited)
    for key in p.nodes:
        print("{:20} {}".format(key, p.nodes[key]))
    print()
    labels = [k for k in p.nodes.keys()]
    print_graphviz(p, labels)
    print_header(p.matrix, labels)
    print_matrix(p.matrix, labels)
    print_header(p.matrix_closure, labels)
    print_matrix(p.matrix_closure, labels)
    print("direct density: {:.0f}%".format(100 * sum([sum(row) for row in p.matrix]) / len(p.matrix)**2))
    print("indirect density: {:.0f}%".format(100 * sum([sum(row) for row in p.matrix_closure]) / len(p.matrix_closure)**2))
    cycles = 0
    for i in range(len(p.matrix_closure)):
        if p.matrix_closure[i][i]:
            cycles += 1
    print("cyclic dependencies: {}".format("yes" if cycles > 0 else "no"))

main()
