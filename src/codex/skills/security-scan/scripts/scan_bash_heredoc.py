"""Here-document recognition for the Bash scrubber (issue #6624).

Split from ``scan_bash_lexer.py`` to keep that module under the file-size limit.
Finds here-document openers, decides whether the body is inert text, and spots
the terminator line.
"""

import re
from collections import deque
from dataclasses import dataclass, replace

# A here-document opener: `<<`, optional `-`, then the delimiter word. Groups
# 2 to 4 are the quoted forms ('X', "X", \X); group 5 is a bare word.
# A bare word is any run of non-metacharacters, so `<<!`, `<<1`, and `1<<2` are
# openers, as in bash. Arithmetic shifts are screened out by the lexer mode.
_HEREDOC_RE = re.compile(
    r"<<(-?)[ \t]*(?:'([^']*)'|\"([^\"]*)\"|\\([^\s;|&<>()'\"\\$`]+)"
    r"|([^\s;|&<>()'\"\\$`]+))"
)


@dataclass(frozen=True, slots=True)
class Heredoc:
    """One pending here-document: where its body ends and whether it is inert text.

    `inert` is set for a quoted delimiter whose body only inert readers consume. The body
    never expands, so the scrubber blanks it.

    `plain` is set for an unquoted delimiter whose body only a print-only reader
    consumes, with no file written. The body expands, but a `$var` there is never a
    word-split argument, so only `$( )` and backtick text stays on the scan.
    """

    delimiter: str
    strip_tabs: bool
    inert: bool
    plain: bool = False


def begin_heredoc(line: str, i: int, out: list[str], pending: deque[Heredoc]) -> int:
    """Consume `<<` at `i`; queue a here-document when a delimiter word follows.

    `<<<` is a here-string, not a here-document. The delimiter word itself is
    left for the normal lexer, which handles its quotes.
    """
    if line.startswith("<<<", i):
        out.append("<<<")
        return i + 3
    match = _HEREDOC_RE.match(line, i)
    if match:
        dash, single, double, escaped, bare = match.groups()
        quoted = single is not None or double is not None or escaped is not None
        word = next(w for w in (single, double, escaped, bare) if w is not None)
        pending.append(Heredoc(word, dash == "-", quoted, plain=not quoted))
    out.append("<<")
    return i + 2


def is_terminator(line: str, heredoc: Heredoc) -> bool:
    """A body ends at a line equal to the delimiter. Trailing blanks do not match."""
    text = line.rstrip("\n")
    if heredoc.strip_tabs:
        text = text.lstrip("\t")
    return text == heredoc.delimiter


# Commands that only store, filter, or print a here-document body. A quoted body
# stays inert only when every command on the opener line is one of these. Any
# other command (su, sudo -i, runuser, chroot, at, source, a shell, a variable
# command word) may run the body, so its lines stay on the per-line scan.
_INERT_READERS = frozenset(
    {
        ":", "true", "echo", "printf", "cat", "tee", "read", "mapfile", "readarray",
        "grep", "egrep", "fgrep", "rg", "sed", "awk", "gawk", "jq", "wc", "sort",
        "uniq", "head", "tail", "tr", "cut", "base64", "git", "gh",
        "python", "python3", "node", "perl", "ruby",
    }
)  # fmt: skip

_SEGMENT_SPLIT_RE = re.compile(r"(\|\||&&|\|&|[;|()`]|(?<![<>])&)")
# Separators after which the next command can still receive the body: a pipe, or
# the close of a substitution whose output becomes command words.
_CARRY_SEPS = frozenset({"|", "|&", ")", "`"})
_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*\+?=")
_REDIRECT_RE = re.compile(r"[0-9]*[<>]")


def _command_word(segment: str) -> str | None:
    """First word of a segment that is not an assignment or a redirection.

    A bare redirection operator (`>`, `2>>`) also skips its target. A redirect
    glued to the word (`cat<<'`) is cut off it. Returns None when no command
    word is visible, as when a quoted command word was blanked by the scrubber.
    """
    skip_next = False
    for token in segment.split():
        if skip_next:
            skip_next = False
        elif _REDIRECT_RE.fullmatch(token):
            skip_next = True
        elif _ASSIGNMENT_RE.match(token):
            continue
        else:
            head = token.split("<")[0].split(">")[0]
            if head and not head.isdigit():
                return head.rsplit("/", 1)[-1]
    return None


def _consumers(opener: str) -> list[str]:
    """Segments that can consume the body.

    That is the segment holding `<<`, later segments joined to it by a pipe or
    a substitution close, and every earlier segment when `<<` sits inside a
    substitution (`eval $(true && cat <<'EOF'`). Commands past a `;`, `&&`, or
    `||` boundary never read the body.
    """
    parts = _SEGMENT_SPLIT_RE.split(opener)
    segments, seps = parts[0::2], parts[1::2]
    owner = next((i for i, seg in enumerate(segments) if "<<" in seg), None)
    if owner is None:
        return []
    before = seps[:owner]
    nested = before.count("(") > before.count(")") or before.count("`") % 2 == 1
    end = owner + 1
    while end < len(segments) and seps[end - 1] in _CARRY_SEPS:
        end += 1
    return segments[0 if nested else owner : end]


def _feeds_shell(opener: str) -> bool:
    """True unless the opener line shows only inert readers consuming the body.

    Fails closed: the segment holding the here-document must name a known inert
    reader, and so must every other consuming segment that names a command. An
    unknown or hidden command word keeps the body on the per-line scan. Segments
    split on `;`, `&`, `|`, parentheses, and backticks, so `eval $(cat <<'EOF'`
    and `cat <<'EOF' | bash` both name a reader outside the list.
    """
    segments = _consumers(opener)
    if not segments:
        return True
    owner = next(s for s in segments if "<<" in s)
    if _command_word(owner) not in _INERT_READERS:
        return True
    return any(
        word is not None and word not in _INERT_READERS for word in map(_command_word, segments)
    )


# Readers that only print or test an unquoted body. A smaller set than
# `_INERT_READERS`: the outer shell expands an unquoted body first, so a reader
# that runs it as code (python, node, perl, ruby, awk -f -, sed e), writes a file
# (tee, sort -o, git, gh), or is unknown keeps the body on the per-line scan.
_TEXT_READERS = frozenset(
    {
        ":", "true", "echo", "printf", "cat", "read", "mapfile", "readarray",
        "grep", "egrep", "fgrep", "rg", "wc", "head", "tail", "tr", "cut", "base64",
    }
)  # fmt: skip

# A descriptor duplication such as `>&2` or `2>&1` writes no file, so it is
# removed before the `>` test.
_FD_DUP_RE = re.compile(r"[0-9]*>&[0-9]+-?")


def _segment_is_print_only(segment: str) -> bool:
    """A print-only reader, or a bare assignment prefix such as `msg=$`."""
    word = _command_word(segment)
    if word is not None:
        return word in _TEXT_READERS
    tokens = segment.split()
    return bool(tokens) and all(_ASSIGNMENT_RE.match(t) for t in tokens)


def _is_print_only(opener: str) -> bool:
    """True when the opener names only print-only readers and writes no file.

    Fails closed. Any `>` (a file or process redirect, `>>`, `&>`, `>(tee x)`)
    keeps the body on the scan, because `cat > gen.sh <<EOF` then `bash gen.sh`
    runs the expanded text. So does any consuming segment whose command word is
    not in `_TEXT_READERS`, which covers `tee`, shells, and interpreters.
    """
    if ">" in _FD_DUP_RE.sub("", opener):
        return False
    segments = _consumers(opener)
    return bool(segments) and all(map(_segment_is_print_only, segments))


def mark_shell_fed(pending: deque[Heredoc], opener: str) -> deque[Heredoc]:
    """Return `pending` with bodies a shell reads no longer inert or plain.

    A quoted delimiter stops the outer shell from expanding the body. When the
    opener line passes the body to anything but a known inert reader (a shell,
    `su`, `sudo -i`, `chroot`, `at`, `source <(`, `$SHELL`), that command may
    run the body, so its unquoted expansions are real.

    An unquoted body stays `plain` only when `_is_print_only` holds.
    """
    if _feeds_shell(opener):
        return deque(replace(h, inert=False, plain=False) for h in pending)
    if not _is_print_only(opener):
        return deque(replace(h, plain=False) for h in pending)
    return pending


def blank_outside_substitutions(line: str) -> tuple[str, bool]:
    """Blank a plain-body line except `$( )` and backtick text; say if it resolved.

    Returns the scrubbed line and whether every substitution and quote closed on
    this line. A backslash escapes the next character, so `\\$(x)` is literal.
    Quotes inside a substitution are tracked so a `)` in a string does not end
    it. When something is still open at end of line, the caller scans the rest
    of the body one line at a time, so nothing after it is hidden.
    """
    body = line.rstrip("\n")
    out: list[str] = []
    depth = 0
    tick = False
    quote = ""
    i = 0
    while i < len(body):
        ch = body[i]
        if depth == 0 and not tick:
            if ch == "\\":
                out.append(" " * len(body[i : i + 2]))
                i += 2
            elif body.startswith("$(", i):
                depth = 1
                out.append("$(")
                i += 2
            else:
                tick = ch == "`"
                out.append("`" if tick else " ")
                i += 1
            continue
        out.append(ch)
        if ch == "\\" and quote != "'":
            out.append(body[i + 1 : i + 2])
            i += 2
            continue
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif tick:
            tick = ch != "`"
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        i += 1
    return "".join(out) + line[len(body) :], depth == 0 and not tick and not quote
