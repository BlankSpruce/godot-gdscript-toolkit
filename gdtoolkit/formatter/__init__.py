import re
from typing import Callable, Iterator, List, Optional, Set, Tuple, Union

from lark import Tree, Token

from ..parser import parser
from .context import Context
from .enum import format_enum


INLINE_COMMENT_OFFSET = 2


def format_code(gdscript_code: str, max_line_length: int) -> str:
    parse_tree = parser.parse(gdscript_code, gather_metadata=True)
    gdscript_code_lines = [
        None,
        *gdscript_code.splitlines(),
    ]  # type: List[Optional[str]]
    comments = _gather_comments_from_code(gdscript_code)
    formatted_lines = []  # type: List[Tuple[Union[None, int], str]]
    context = Context(
        indent=0,
        previously_processed_line_number=0,
        max_line_length=max_line_length,
        gdscript_code_lines=gdscript_code_lines,
        comments=comments,
    )
    formatted_lines, _ = _format_block(
        parse_tree.children, _format_class_statement, context
    )
    formatted_lines.append((None, ""))
    formatted_lines_with_inlined_comments = _add_inline_comments(
        formatted_lines, comments
    )
    return "\n".join([line for _, line in formatted_lines_with_inlined_comments])


def _format_block(
    statements: List, statement_formatter: Callable, context: Context,
) -> Tuple[List, int]:
    formatted_lines = []  # type: List
    previously_processed_line_number = context.previously_processed_line_number
    for statement in statements:
        blank_lines = _reconstruct_blank_lines_in_range(
            previously_processed_line_number, statement.line, context,
        )
        if previously_processed_line_number == context.previously_processed_line_number:
            blank_lines = _remove_empty_strings_from_begin(blank_lines)
        formatted_lines += blank_lines
        lines, previously_processed_line_number = statement_formatter(
            statement, context
        )
        formatted_lines += lines
    dedent_line_number = _find_dedent_line_number(
        previously_processed_line_number, context
    )
    lines_at_the_end = _reconstruct_blank_lines_in_range(
        previously_processed_line_number, dedent_line_number, context,
    )
    lines_at_the_end = _remove_empty_strings_from_end(lines_at_the_end)
    formatted_lines += lines_at_the_end
    previously_processed_line_number = dedent_line_number - 1
    return (formatted_lines, previously_processed_line_number)


def _format_class_statement(
    statement: Union[Tree, Token], context: Context
) -> Tuple[List, int]:
    formatted_lines = []
    last_processed_line_no = statement.line
    if statement.data == "tool_stmt":
        formatted_lines.append((statement.line, "{}tool".format(" " * context.indent)))
    elif statement.data == "class_def":
        name = statement.children[0].value
        formatted_lines.append(
            (statement.line, "{}class {}:".format(" " * context.indent, name))
        )
        class_lines, last_processed_line_no = _format_block(
            statement.children[1:],
            _format_class_statement,
            context.create_child_context(last_processed_line_no),
        )
        formatted_lines += class_lines
    elif statement.data == "func_def":
        name = statement.children[0].value
        formatted_lines.append(
            (statement.line, "{}func {}():".format(" " * context.indent, name))
        )
        func_lines, last_processed_line_no = _format_block(
            statement.children[1:],
            _format_func_statement,
            context.create_child_context(last_processed_line_no),
        )
        formatted_lines += func_lines
    elif statement.data == "enum_def":
        enum_lines, last_processed_line_no = format_enum(statement, context)
        formatted_lines += enum_lines
    return (formatted_lines, last_processed_line_no)


def _format_func_statement(
    statement: Union[Tree, Token], context: Context
) -> Tuple[List, int]:
    formatted_lines = []
    last_processed_line_no = statement.line
    if statement.data == "pass_stmt":
        formatted_lines.append((statement.line, "{}pass".format(" " * context.indent)))
    return (formatted_lines, last_processed_line_no)


def _find_dedent_line_number(previously_processed_line_number: int, context: Context):
    if (
        previously_processed_line_number == len(context.gdscript_code_lines) - 1
        or context.indent == 0
    ):
        return len(context.gdscript_code_lines)
    line_no = previously_processed_line_number + 1
    for line in context.gdscript_code_lines[previously_processed_line_number + 1 :]:
        if re.search(r"^ {0,%d}[^ ]+" % (context.indent - 1), line) is not None:
            break
        line_no += 1
    for line in context.gdscript_code_lines[line_no - 1 :: -1]:
        if line == "":  # TODO: all ws-lines (non-code&non-comment)
            line_no -= 1
        else:
            break
    return line_no


def _gather_comments_from_code(gdscript_code: str) -> List:
    lines = gdscript_code.splitlines()
    comments = [None]  # type: List[Optional[str]]
    for line in lines:
        comment_start = line.find("#")
        if comment_start >= 0:
            comments.append(line[comment_start:])
        else:
            comments.append(None)
    return comments


def _reconstruct_blank_lines_in_range(begin: int, end: int, context: Context) -> List:
    comments = context.comments
    prefix = " " * context.indent
    comments_in_range = comments[begin + 1 : end]
    reconstructed_lines = ["" if c is None else prefix + c for c in comments_in_range]
    reconstructed_lines = _squeeze_lines(reconstructed_lines)
    reconstructed_lines = list(
        zip([None for _ in range(begin + 1, end)], reconstructed_lines)
    )

    return reconstructed_lines


def _squeeze_lines(lines: List[str]) -> List[str]:
    squeezed_lines = []
    previous_line = None
    for line in lines:
        if line != "" or previous_line != "":
            squeezed_lines.append(line)
        previous_line = line
    return squeezed_lines


def _remove_empty_strings_from_begin(lst: List) -> List:
    for i, el in enumerate(lst):
        if el[1] != "":
            return lst[i:]
    return []


def _remove_empty_strings_from_end(lst: List) -> List:
    return list(reversed(_remove_empty_strings_from_begin(list(reversed(lst)))))


def _add_inline_comments(formatted_lines: List, comments: List) -> Iterator:
    added_comment_indexes = set()  # type: Set[int]

    def _append_comment(line, line_number):
        if (
            line_number not in added_comment_indexes
            and line_number is not None
            and comments[line_number] is not None
        ):
            added_comment_indexes.add(line_number)
            return "{}{}{}".format(
                line, " " * INLINE_COMMENT_OFFSET, comments[line_number]
            )
        return line

    return reversed(
        [
            (line_no, _append_comment(line, line_no))
            for line_no, line in reversed(formatted_lines)
        ]
    )
