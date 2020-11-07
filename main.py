from enum import Enum
import sys
import re

#
# This is a tool to analyze dependencies within a codebase.
# This code does the absolute bare-minimum C parsing in order to understand include directives.
# No macros are expanded and no conditionals are evaluated.
# There are better and more optimal ways to implement this all, however, it does it's job! And it
# does it well (at least for small codebases). Not a whole lot of value in optimizing an
# inconsequential script.
#
# This was made by Jeremy Rifkin in November 2020
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
	while i < len(string):
		if string[i] == "\\" and i < len(string) - 1 and string[i + 1] == "\n":
			i += 2
		else:
			translated_string += string[i]
			i += 1
	return translated_string

# lexer rules
lexer_rules = [
	"COMMENT", r"//.*(?:\n|$)",
	"MCOMMENT", r"/\*(?s:.)*\*/",
	"IDENTIFIER", r"[a-zA-Z_$][a-zA-Z0-9_$]*",
	"NUMBER", r"(?:0x|0b)?[0-9a-fA-F]+(?:.[0-9a-fA-F]+)?(?:[eEpP][0-9a-fA-F]+)?(?:u|U|l|L|ul|UL|ll|LL|ull|ULL|f|F)",
	"STRING", r"\"(\\.|[^\"\\])*\"",
	"CHAR", r"'(\\.|[^\"\\])'",
	"PREPROCESSING_DIRECTIVE", r"(?:#|%:)[a-z]+",
	"PUNCTUATION", r"[,.<>?/=;:~!#%^&*(){}\[\]]",
	"WHITESPACE", r"\s+"
]
lexer_ignores = {"COMMENT", "MCOMMENT", "WHITESPACE"}
lexer_regex = ""
class Token:
	def __init__(self, token, value):
		self.token = token
		self.value = value
		# only digraph that needs to be handled
		if token == "PREPROCESSING_DIRECTIVE":
			self.value = re.sub(r"^%:", "#", value)
	def __repr__(self):
		return "{} {}".format(self.token, self.value).strip()
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
	while True:
		if i >= len(string) - 1:
			break
		m = lexer_regex.match(string, i)
		if m:
			groupname = m.lastgroup
			if groupname not in lexer_ignores:
				tokens.append(Token(groupname, m.group(groupname)))
			i = m.end()
		else:
			print(string)
			print(i)
			print(tokens)
			raise Exception("shit")
	return tokens

def phase_four(string):
	# preprocessing
	pass

def process_file(file):
	#
	# There are better ways to do the input processing that would allow looping though the input only
	# once and not using extra memory, but it won't make enough of a performance difference to warrant.
	# At least for now.
	#
	# All that's needed is understanding #include directives in a file. In order to do that, only
	# primitive and bare-minimum tokenization is required.
	#
	content = None
	with open(file, "r") as f:
		content = f.read()
	print(content)
	print("-" * 20)
	content = phase_one(content)
	print(content)
	print("-" * 20)
	content = phase_two(content)
	print(content)
	print("-" * 20)
	tokens = phase_three(content)
	print(tokens)

def main():
	# <startfile> [search directories]
	if len(sys.argv) == 1:
		print_help()
		return
	if sys.argv[1] == "-h" or sys.argv[1] == "--help":
		print_help()
		return
	root = sys.argv[1]
	path = sys.argv[2:]

	init_lexer()
	process_file(root)

main()

