import sys

def print_help():
	print("Ussage: python main.py <startfile> [search directories]")

def phase_one(string):
	# trigraphs
	pass
def phase_two(string):
	# backslash followed immediately by newline
	pass
def phase_three(string):
	# tokenization
	pass
def phase_four(string):
	# preprocessing
	pass

def process_file(file):
	with open(file, "r") as f:
		print(f.read())


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

	process_file(root)

main()

