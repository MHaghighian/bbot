import re
import logging

log = logging.getLogger("bbot.core.helpers.yara")

try:
    import yara

    _HAS_YARA = True
except ImportError:
    yara = None
    _HAS_YARA = False
    log.debug("yara-python not installed; using regex fallback for string matching")


class _RegexCompiledRule:
    """Minimal stand-in for a compiled YARA rule when yara-python is unavailable."""

    def __init__(self, patterns):
        self._patterns = patterns

    def match(self, data=None, **kwargs):
        if data is None:
            return []
        if isinstance(data, bytes):
            try:
                text = data.decode("utf-8", errors="ignore")
            except Exception:
                text = ""
        else:
            text = str(data)

        class _Instance:
            def __init__(self, matched):
                self.matched_data = matched.encode("utf-8")

        class _StringMatch:
            def __init__(self, matched):
                self.instances = [_Instance(matched)]

        class _Match:
            def __init__(self, matched_strings):
                self.strings = [_StringMatch(s) for s in matched_strings]

        found = []
        for pat, nocase, original in self._patterns:
            flags = re.IGNORECASE if nocase else 0
            if re.search(pat, text, flags=flags):
                found.append(original)
        if found:
            return [_Match(found)]
        return []


class YaraHelper:
    def __init__(self, parent_helper):
        self.parent_helper = parent_helper
        self.has_yara = _HAS_YARA

    def compile_strings(self, strings: list[str], nocase=False):
        """
        Compile a list of strings into a YARA rule (or regex fallback).
        """
        if not _HAS_YARA:
            patterns = []
            for s in strings:
                patterns.append((re.escape(s), nocase, s))
            return _RegexCompiledRule(patterns)

        # Format each string as a YARA string definition
        yara_strings = []
        for i, s in enumerate(strings):
            s = s.replace('"', '\\"')
            yara_string = f'$s{i} = "{s}"'
            if nocase:
                yara_string += " nocase"
            yara_strings.append(yara_string)
        yara_strings = "\n        ".join(yara_strings)

        # Create the complete YARA rule
        yara_rule = f"""
rule strings_match
{{
    strings:
        {yara_strings}
    condition:
        any of them
}}
"""
        # Compile and return the rule
        return self.compile(source=yara_rule)

    def compile(self, *args, **kwargs):
        if not _HAS_YARA:
            source = kwargs.get("source") or (args[0] if args else "")
            # Best-effort: extract quoted strings from a YARA source blob
            found = re.findall(r'=\s*"((?:\\.|[^"\\])*)"', source or "")
            patterns = [(re.escape(bytes(s, "utf-8").decode("unicode_escape")), False, s) for s in found]
            return _RegexCompiledRule(patterns)
        return yara.compile(*args, **kwargs)

    async def match(self, compiled_rules, text):
        """
        Given a compiled YARA rule and a body of text, return a list of strings that match the rule
        """
        matched_strings = []
        matches = await self.parent_helper.run_in_executor_cpu(compiled_rules.match, data=text)
        if matches:
            for match in matches:
                for string_match in match.strings:
                    for instance in string_match.instances:
                        matched_string = instance.matched_data.decode("utf-8")
                        matched_strings.append(matched_string)
        return matched_strings
