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
	"STRING", r"\"(\\.|[^\"\\])*\"",
	"CHAR", r"'(\\.|[^\"\\])'",
	"PREPROCESSING_DIRECTIVE", r"(?:#|%:)[a-z]+",
	"PUNCTUATION", r"[,.<>?/=;:~!#%^&*\-+(){}\[\]]",
	"NEWLINE", r"\n",
	"WHITESPACE", r"[^\S\n]+" #r"\s+"
]
lexer_ignores = {"COMMENT", "MCOMMENT", "WHITESPACE"}
lexer_regex = ""
class Token:
	def __init__(self, token_type, value, line):
		self.token_type = token_type
		self.value = value
		self.line = line
		# only digraph that needs to be handled
		if token_type == "PREPROCESSING_DIRECTIVE":
			self.value = re.sub(r"^%:", "#", value)
		elif token_type == "NEWLINE":
			self.value = ""
	def __repr__(self):
		if self.value == "":
			return "{} {}".format(self.token_type, self.line)
		else:
			return "{} {} {}".format(self.token_type, self.value, self.line)
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
				tokens.append(Token(groupname, m.group(groupname), line))
			if groupname == "NEWLINE":
				line += 1
			if groupname == "MCOMMENT":
				line += m.group(groupname).count("\n")
			i = m.end()
		else:
			print(string)
			print(i)
			print(tokens)
			print("\n\n{}\n\n".format(string[i:i+20]))
			raise Exception("lexer error")
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
	

def process_file(file):
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
	with open(file, "r") as f:
		content = f.read()
	print(content)
	print("-" * 20)
	# trigraphs
	content = phase_one(content)
	print(content)
	print("-" * 20)
	# backslash newline
	content = phase_two(content)
	print(content)
	print("-" * 20)
	# tokenize
	tokens = phase_three(content)
	#print(tokens)
	for token in tokens:
		print(token)
	print("-" * 20)
	# process the file
	while len(tokens) > 0:
		token = tokens.pop(0)
		if token.token_type == "PREPROCESSING_DIRECTIVE" and token.value == "#include":
			if len(tokens) == 0:
				raise Exception("parse error: expected token following #include directive, found nothing")
			elif peek_tokens(tokens, ("STRING", "NEWLINE")):
				print("#include", tokens[:2])
			elif peek_tokens(tokens, (("PUNCTUATION", "<"), "IDENTIFIER", ("PUNCTUATION", ">"), "NEWLINE")):
				print("#include", tokens[:4])
			else:
				raise Exception("parse error: unexpected token sequence after #include directive. This may be a valid preprocessing directive and shortcoming of the preprocessor {}.".format(token.line))
		else:
			pass

def main():
	# <startfile> [search directories]
	argv = sys.argv
	#argv = ["main.py", "test.c"]
	if len(argv) == 1:
		print_help()
		return
	if argv[1] == "-h" or argv[1] == "--help":
		print_help()
		return
	root = argv[1]
	path = argv[2:]

	init_lexer()
	process_file(root)

main()

