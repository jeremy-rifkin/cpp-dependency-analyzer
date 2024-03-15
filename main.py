import argparse
import colorama
from enum import Enum
import os
import re
import sys
import json
import math

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
    ("COMMENT", r"//.*(?=\n|$)"),
    ("MCOMMENT", r"/\*(?:(?!\*/)[\s\S])*\*/"), #r"/\*(?s:.)*\*/"),
    ("RAW_STRING", r"(R\"([^ ()\t\r\v\n]*)\((?P<RAW_STRING_CONTENT>(?:(?!\)\5\").)*)\)\5\")"),
    ("IDENTIFIER", r"[a-zA-Z_$][a-zA-Z0-9_$]*"),
    ("NUMBER", r"[0-9]([eEpP][\-+]?[0-9a-zA-Z.']|[0-9a-zA-Z.'])*"), # basically a ppnumber regex # r"(?:0x|0b)?[0-9a-fA-F]+(?:.[0-9a-fA-F]+)?(?:[eEpP][0-9a-fA-F]+)?(?:u|U|l|L|ul|UL|ll|LL|ull|ULL|f|F)?",
    ("STRING", r"\"(?P<STRING_CONTENT>(?:\\x[0-7]+|\\.|[^\"\\])*)\""),
    ("CHAR", r"'(\\x[0-9a-fA-F]+|\\.|[^\'\\])'"),
    ("PREPROCESSING_DIRECTIVE", r"(?:#|%:)[a-z]+"),
    ("PUNCTUATION", r"[,.<>?/=;:~!#%^&*\-\+|\(\)\{\}\[\]]"),
    ("NEWLINE", r"\n"),
    ("WHITESPACE", r"[^\S\n]+") #r"\s+"
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
    # for i in range(0, len(lexer_rules), 2):
    #     name = lexer_rules[i]
    #     pattern = lexer_rules[i + 1]
    for name, pattern in lexer_rules:
        lexer_regex += ("" if lexer_regex == "" else "|") + "(?P<{}>{})".format(name, pattern)
    # print(lexer_regex)
    lexer_regex = re.compile(lexer_regex)
init_lexer()

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
                elif groupname == "RAW_STRING":
                    tokens.append(Token(groupname, m.group("RAW_STRING_CONTENT"), line, i))
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
    reason = ""
    if len(tokens) < len(seq):
        good = False
        reason = "EOF"
    else:
        for i, token in enumerate(seq):
            if type(seq[i]) is tuple:
                if not (tokens[i].token_type == seq[i][0] and tokens[i].value == seq[i][1]):
                    good = False
                    reason = "{}".format(tokens[i].token_type)
                    break
            elif tokens[i].token_type != seq[i]:
                good = False
                reason = "{}".format(tokens[i].token_type)
                break
    if not good:
        if expected is not None:
            raise Exception("parse error: expected {} after {} on line {}, found [{}, ...], failed due to {}".format(expected, after, line, tokens[0], reason))
        else:
            raise Exception("parse error: unexpected tokens following {} on line {}, failed due to {}".format(after, line, reason))

def parse_includes(path: str) -> list:
    # get file contents
    with open(path, "r") as f:
        content = f.read()
    # trigraphs
    content = phase_one(content)
    # backslash newline
    content = phase_two(content)
    # tokenize
    tokens = phase_three(content)

    # print(tokens)
    # return

    # process the file
    # Preprocessor directives are only valid if they are at the beginning of a line. Code makes
    # sure the next token is always at the start of the line going into each loop iteration.
    includes = [] # files queued up to process so that logic doesn't get put in the middle of the parse logic
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
                includes.append(path_token.value)
                # self.queue_all(process_queue, os.path.join(os.path.dirname(file_path), path_token.value))
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
                ## # library includes won't be traversed
                print("{} #include <{}>".format(line, path))
                includes.append(path)
            elif peek_tokens(tokens, ("IDENTIFIER", )):
                identifier = tokens.pop(0)
                expect(tokens, ("NEWLINE", ), line, "#include declaration")
                print("Warning: Ignoring #include {}".format(identifier.value))
            else:
                raise Exception("parse error: unexpected token sequence after #include directive on line {}. This may be a valid preprocessing directive and reflect a shortcoming of this parser.".format(line))
        else:
            # need to consume the whole line of tokens
            while token.token_type != "NEWLINE" and len(tokens) > 0:
                token = tokens.pop(0)
    return includes

class Analysis:
    def __init__(self, excludes: list, sentinels: list):
        self.excludes = excludes
        self.sentinels = sentinels
        self.not_found = set()
        self.visited = set() # set of absolute paths
        # absolute path -> { i: number, dependencies: list[absolute path]}
        self.nodes = {}
        # self.process_file(file_path)

    def resolve_include(self, base: str, file_path: str, search_paths: list):
        # search paths: first search relative, then via the paths
        relative = os.path.join(
            os.path.dirname(base),
            file_path
        )
        if os.path.exists(relative):
            print("        Found:", relative)
            return os.path.abspath(relative)
        else:
            for search_path in search_paths:
                path = os.path.join(
                    search_path,
                    file_path
                )
                if os.path.exists(path):
                    print("        Found:", path)
                    return os.path.abspath(path)

    def process_include(self, base: str, file_path: str, search_paths: list):
        resolved = self.resolve_include(base, file_path, search_paths)
        if resolved:
            print("Recursing into {}".format(file_path))
            self.process_file(resolved, search_paths)
            return resolved
        else:
            self.not_found.add(file_path)
            return None

    def process_file(self, path: str, search_paths: list):
        if path in self.visited:
            return
        for exclude in self.excludes:
            if path.startswith(exclude):
                return
        self.visited.add(path)
        includes = parse_includes(path)
        # print(path)
        print("    Adding includes:", includes)
        dependencies = set()
        for include in includes:
            resolved = self.process_include(path, include, search_paths)
            if resolved is not None:
                dependencies.add(resolved)
            elif include in self.sentinels:
                if include not in self.nodes:
                    self.nodes[include] = {
                        "i": len(self.nodes),
                        "dependencies": set()
                    }
                dependencies.add(include)

        self.nodes[path] = {
            "i": len(self.nodes),
            "dependencies": dependencies
        }

    def build_matrix(self):
        N = len(self.nodes)
        self.matrix = [[0 for _ in range(N)] for _ in range(N)]
        for key in self.nodes:
            node = self.nodes[key]
            row = node["i"]
            for d in node["dependencies"]:
                if d in self.nodes:
                    self.matrix[row][self.nodes[d]["i"]] = 1
        # deep copy
        self.matrix_closure = [[col for col in row] for row in self.matrix]
        G = self.matrix_closure
        # floyd-warshall
        for k in range(N):
            for i in range(N):
                for j in range(N):
                    G[i][j] = G[i][j] or (G[i][k] and G[k][j])

def print_header(matrix, labels):
    print(" " * 50, end="")
    for i in range(len(matrix)):
        print(" {}".format(os.path.basename(labels[i])[0]), end="")
    print()

def print_matrix(matrix, labels):
    color = os.isatty(1)
    for i, row in enumerate(matrix):
        print("{:>50} ".format(os.path.basename(labels[i])), end="")
        for j, n in enumerate(row):
            if i == j:
                print("{}{}{} ".format(colorama.Fore.BLUE if color else "", "#" if n else "~", colorama.Style.RESET_ALL if color else ""), end="")
            else:
                print("{} ".format("#" if n else "~"), end="")
        print()
    print()

def count_incident_edges(matrix, labels, tu_only=False):
    counts = {} # label -> count
    for col in range(len(matrix)):
        for row in range(len(matrix)):
            # if the row is not a .c/.cpp file, it's a header so ignore it
            if tu_only and not (labels[row].endswith(".cpp") or labels[row].endswith(".c")):
                continue
            if matrix[row][col]:
                if labels[col] in counts:
                    counts[labels[col]] += 1
                else:
                    counts[labels[col]] = 1
    return counts

def print_graphviz(analysis: Analysis, labels: list):
    print("digraph G {")
    #print("\tnodesep=0.3;")
    #print("\tranksep=0.2;")
    #print("\tnode [shape=circle, fixedsize=true];")
    #print("\tedge [arrowsize=0.8];")
    #print("\tlayout=fdp;")

    # counts = count_incident_edges(analysis.matrix, labels, True)
    counts = count_incident_edges(analysis.matrix_closure, labels, True)
    max_count = max(counts.values())
    def get_count_color(label: str):
        if label in counts:
            return min(int(math.floor((counts[label] / max_count) * 9)) + 1, 9)
        else:
            return "white"
    print("\tsubgraph cluster_{} {{".format("direct"))
    print("\t\tnode [colorscheme=reds9] # Apply colorscheme to all nodes")
    print("\t\tlabel=\"{}\";".format("direct dependencies"))
    for i in range(len(labels)):
        print("\t\tn{} [label=\"{}\", fillcolor={}, style=\"filled,solid\"];".format(i, os.path.basename(labels[i]), get_count_color(labels[i])))
    print("\t\t", end="")
    for i, row in enumerate(analysis.matrix):
        for j, v in enumerate(row):
            if v:
                print("n{}->n{};".format(i, j), end="")
    print()
    print("\t}")

    offset = len(labels)
    # counts = count_incident_edges(analysis.matrix_closure, labels, True)
    # max_count = max(counts.values())
    # def get_count_color(label: str):
    #     if label in counts:
    #         return min(int(math.floor((counts[label] / max_count) * 10)), 9)
    #     else:
    #         return "white"
    print("\tsubgraph cluster_{} {{".format("indirect"))
    print("\t\tnode [colorscheme=reds9] # Apply colorscheme to all nodes")
    print("\t\tlabel=\"{}\";".format("dependency transitive closure"))
    for i in range(len(labels)):
        print("\t\tn{} [label=\"{}\", fillcolor={}, style=\"filled,solid\"];".format(i + offset, os.path.basename(labels[i]), get_count_color(labels[i])))
    print("\t\t", end="")
    for i, row in enumerate(analysis.matrix_closure):
        for j, v in enumerate(row):
            if v:
                print("n{}->n{}[color={}];".format(i + offset, j + offset, "black" if analysis.matrix[i][j] else "orange"), end="")
    print()
    print("\t}")
    print("}")

def parse_search_paths(command: str) -> list:
    paths = [x.group(1) for x in re.finditer(r"-I([^ ]+)", command)]
    # print("Search paths:", paths)
    return paths

def file_path(string):
    if os.path.isfile(string):
        return string
    else:
        raise RuntimeError(f"Invalid file path {string}")

def dir_path(string):
    if os.path.isdir(string):
        return string
    else:
        raise RuntimeError(f"Invalid directory {string}")

def main():
    parser = argparse.ArgumentParser(
        prog="cpp-dependency-analyzer",
        description="Analyze C++ transitive dependencies"
    )
    parser.add_argument(
        "--compile-commands",
        type=file_path,
        required=True
    )
    # parser.add_argument(
    #     "--pwd",
    #     type=dir_path,
    # )
    parser.add_argument('--exclude', action='append', nargs=1)
    parser.add_argument('--sentinel', action='append', nargs=1)
    args = parser.parse_args()

    excludes = []
    if args.exclude:
        # print(args.exclude)
        for exclude in args.exclude:
            abspath = os.path.abspath(exclude[0])
            if os.path.isdir(abspath):
                excludes.append(abspath + os.path.sep)
            else:
                excludes.append(abspath)
    sentinels = []
    if args.sentinel:
        sentinels = [s[0] for s in args.sentinel]
    print(excludes, sentinels)

    # if args.pwd:
    #     os.chdir(args.pwd)

    with open(args.compile_commands, "r") as f:
        compile_commands = json.load(f)

    analysis = Analysis(excludes, sentinels)

    for entry in compile_commands:
        os.chdir(entry["directory"])
        print("From compile commands:", entry["file"])
        # entry["command"] ...
        analysis.process_file(os.path.abspath(entry["file"]), parse_search_paths(entry["command"]))

    # init_lexer()
    # p = Processor(root)

    # this is mainly for dev/debugging; make sure no components are missed in traversal
    #print("visited: ", p.visited)
    #print("all: ", p.all_files)
    # print("xor: ", p.all_files ^ p.visited)
    print("missed:", analysis.not_found)
    for key in analysis.nodes:
        print("{:20} {}".format(key, analysis.nodes[key]))
    print()

    analysis.build_matrix()

    labels = [k for k in analysis.nodes.keys()]
    print_graphviz(analysis, labels)
    print_header(analysis.matrix, labels)
    print_matrix(analysis.matrix, labels)
    print_header(analysis.matrix_closure, labels)
    print_matrix(analysis.matrix_closure, labels)
    print("direct density: {:.0f}%".format(100 * sum([sum(row) for row in analysis.matrix]) / len(analysis.matrix)**2))
    print("indirect density: {:.0f}%".format(100 * sum([sum(row) for row in analysis.matrix_closure]) / len(analysis.matrix_closure)**2))
    cycles = 0
    for i in range(len(analysis.matrix_closure)):
        if analysis.matrix_closure[i][i]:
            cycles += 1
    print("cyclic dependencies: {}".format("yes" if cycles > 0 else "no"))

    matrix_counts = count_incident_edges(analysis.matrix, labels)
    print("Dependency counts:")
    for name, count in matrix_counts.items():
        print(os.path.basename(name), count)

    matrix_closure_counts = count_incident_edges(analysis.matrix_closure, labels)
    print("Transitive dependency counts:")
    for name, count in matrix_closure_counts.items():
        print(os.path.basename(name), count)

    matrix_counts = count_incident_edges(analysis.matrix, labels, True)
    print("Dependency counts (TU-only):")
    for name, count in matrix_counts.items():
        print(os.path.basename(name), count)

    matrix_closure_counts = count_incident_edges(analysis.matrix_closure, labels, True)
    print("Transitive dependency counts (TU-only):")
    for name, count in matrix_closure_counts.items():
        print(os.path.basename(name), count)

main()
