"""Core tests: XML parsing and saving. Reading rows and the header, escaping, corruption cases, line
endings, unchanged rows, the atomic save and row removal. Every test that checks a saved file's
structure ends with the independent oracle, core_support.assert_xml_intact().

Run:  python tests/check_core_xml.py      (exit code 0 = all passed)
"""

import core_support as cs  # first: offscreen Qt, scratch working folder, isolated caches

import difflib
import os
import sys
import unittest
from pathlib import Path
from typing import Callable, List, Tuple
from unittest import mock

xte = cs.xte


def _parse(text: str, name: str = "file.xml") -> Tuple[Path, List[str], list]:
    """Write *text* byte for byte into a fresh folder and parse it: (path, segments, entries)."""
    path = cs.write_exact(cs.temp_dir() / name, text)
    segments, entries, *_ = xte.parse_file(path)
    return path, segments, entries


def _save(text: str, edit: Callable[[list], None] = lambda entries: None,
          name: str = "file.xml") -> Path:
    """Parse *text*, apply *edit* to the entries, save; returns the saved file's path."""
    path, segments, entries = _parse(text, name)
    edit(entries)
    xte.save_file(path, segments, entries)
    return path


def _set(index: int, **fields) -> Callable[[list], None]:
    """An edit that sets *fields* on entries[index]."""
    def edit(entries: list) -> None:
        for key, value in fields.items():
            setattr(entries[index], key, value)
    return edit


SAVE_ROW = cs.row("Save", "Saglabāt", translator="Jane", status="Review", istablet="true")
CANCEL_ROW = cs.row("Cancel", "Atcelt")
BARE_ROW = '    <string name="M">m</string>\n'


class ParseTests(unittest.TestCase):
    def test_row_values_are_read(self):
        _, _, entries = _parse(cs.xml_doc([SAVE_ROW]))
        expected = xte.StringEntry("Save", "Jane", "Review", cs.DEFAULT_DATE, "true", "Saglabāt",
                                   seg_idx=1)
        self.assertEqual(entries[0], expected)

    def test_missing_status_reads_as_new(self):
        _, _, entries = _parse(cs.xml_doc([BARE_ROW]))
        self.assertEqual(entries[0].status, "New")

    def test_missing_istablet_reads_as_false(self):
        _, _, entries = _parse(cs.xml_doc([BARE_ROW]))
        self.assertEqual(entries[0].istablet, "false")

    def test_header_values_are_read(self):
        path = cs.write_exact(cs.temp_dir() / "file.xml", cs.xml_doc([SAVE_ROW]))
        _, _, culture, language, version = xte.parse_file(path)
        self.assertEqual((culture, language, version), ("lv-LV", "Latviešu", "4.1.1140"))

    def test_entities_are_unescaped_in_the_name(self):
        raw = '    <string name="a &amp; &lt;b&gt; &quot;c&quot;">x</string>\n'
        _, _, entries = _parse(cs.xml_doc([raw]))
        self.assertEqual(entries[0].name, 'a & <b> "c"')

    def test_entities_are_unescaped_in_the_text(self):
        raw = '    <string name="E">a &amp; &lt;b&gt; &quot;c&quot;</string>\n'
        _, _, entries = _parse(cs.xml_doc([raw]))
        self.assertEqual(entries[0].text, 'a & <b> "c"')

    def test_multiline_text_is_read(self):
        _, _, entries = _parse(cs.xml_doc([cs.row("Two", "line 1\nline 2")]))
        self.assertEqual(entries[0].text, "line 1\nline 2")

    def test_latvian_characters_are_read(self):
        _, _, entries = _parse(cs.xml_doc([cs.row("Ābols", "ĀČĒĢĪĶĻŅŠŪŽ āčēģīķļņšūž")]))
        self.assertEqual((entries[0].name, entries[0].text), ("Ābols", "ĀČĒĢĪĶĻŅŠŪŽ āčēģīķļņšūž"))

    def test_seg_idx_values_are_odd_and_increasing(self):
        _, _, entries = _parse(cs.xml_doc([SAVE_ROW, CANCEL_ROW, cs.row("Open", "Atvērt")]))
        self.assertEqual([e.seg_idx for e in entries], [1, 3, 5])


class EscapingTests(unittest.TestCase):
    def test_ampersand_and_angle_brackets_are_escaped_in_text(self):
        path = _save(cs.xml_doc([SAVE_ROW]), _set(0, text="a & b < c > d"))
        self.assertIn(">a &amp; b &lt; c &gt; d</string>", path.read_text(encoding="utf-8"))

    def test_quotes_are_literal_in_text(self):
        path = _save(cs.xml_doc([SAVE_ROW]), _set(0, text='say "hi", it\'s'))
        self.assertIn('>say "hi", it\'s</string>', path.read_text(encoding="utf-8"))

    def test_double_quote_is_escaped_in_an_attribute(self):
        path = _save(cs.xml_doc([SAVE_ROW]), _set(0, translator='Jo "J" O\'Brien'))
        self.assertIn('translator="Jo &quot;J&quot; O\'Brien"', path.read_text(encoding="utf-8"))

    def test_apostrophe_is_never_written_as_a_numeric_entity(self):
        path = _save(cs.xml_doc([SAVE_ROW]), _set(0, translator="O'Brien", text="it's"))
        self.assertNotIn("&#x27;", path.read_text(encoding="utf-8"))

    def test_markup_in_text_saves_an_intact_file(self):
        for text in ("</string>", '<string name="x">', "]]>", "<![CDATA[x]]>"):
            with self.subTest(text=text):
                path = _save(cs.xml_doc([SAVE_ROW, CANCEL_ROW]), _set(0, text=text))
                cs.assert_xml_intact(self, path, ["Save", "Cancel"])

    def test_markup_in_text_reads_back_unchanged(self):
        for text in ("</string>", '<string name="x">', "]]>", "<![CDATA[x]]>"):
            with self.subTest(text=text):
                path = _save(cs.xml_doc([SAVE_ROW]), _set(0, text=text))
                self.assertEqual(xte.parse_file(path)[1][0].text, text)


class HeaderTests(unittest.TestCase):
    def test_header_edit_survives_save_and_reopen(self):
        path, segments, entries = _parse(cs.xml_doc([SAVE_ROW]))
        segments[0] = xte.build_header_xml(segments[0], "Latviešu 2", "4.2.7")
        xte.save_file(path, segments, entries)
        self.assertEqual(xte.parse_xml_header(path), ("lv-LV", "Latviešu 2", "4.2.7"))



SELF_CLOSING_ROW = '    <string name="S" translator="" status="New" modifyDate="" istablet="false"/>\n'
RAW_GT_ROW = ('    <string name="a > b" translator="Jane" status="New" modifyDate="" '
              'istablet="false">t</string>\n')
DATA_NAME_ROW = ('    <string data-name="Other" name="Save" translator="" status="New" '
                 'modifyDate="" istablet="false">s</string>\n')
EMPTY_ROW = '    <string name="E" translator="" status="New" modifyDate="" istablet="false"></string>\n'


class CorruptionTests(unittest.TestCase):
    def test_self_closing_row_does_not_swallow_the_next_row(self):
        _, _, entries = _parse(cs.xml_doc([SELF_CLOSING_ROW, CANCEL_ROW]))
        self.assertEqual([e.name for e in entries], ["S", "Cancel"])

    def test_self_closing_row_reads_empty_text(self):
        _, _, entries = _parse(cs.xml_doc([SELF_CLOSING_ROW, CANCEL_ROW]))
        self.assertEqual(entries[0].text, "")

    def test_self_closing_row_survives_an_unchanged_save(self):
        path = _save(cs.xml_doc([SELF_CLOSING_ROW, CANCEL_ROW]))
        cs.assert_xml_intact(self, path, ["S", "Cancel"])

    def test_self_closing_row_stays_self_closing_while_empty(self):
        path = _save(cs.xml_doc([SELF_CLOSING_ROW, CANCEL_ROW]), _set(0, status="Review"))
        self.assertIn('status="Review" modifyDate="" istablet="false"/>',
                      path.read_text(encoding="utf-8"))

    def test_self_closing_row_gets_an_end_tag_once_it_has_text(self):
        path = _save(cs.xml_doc([SELF_CLOSING_ROW, CANCEL_ROW]), _set(0, text="Jauns"))
        self.assertIn('istablet="false">Jauns</string>', path.read_text(encoding="utf-8"))

    def test_self_closing_row_with_new_text_saves_an_intact_file(self):
        path = _save(cs.xml_doc([SELF_CLOSING_ROW, CANCEL_ROW]), _set(0, text="Jauns"))
        cs.assert_xml_intact(self, path, ["S", "Cancel"])

    def test_raw_gt_in_an_attribute_does_not_end_the_tag(self):
        _, _, entries = _parse(cs.xml_doc([RAW_GT_ROW, CANCEL_ROW]))
        self.assertEqual([e.name for e in entries], ["a > b", "Cancel"])

    def test_raw_gt_row_text_is_read(self):
        _, _, entries = _parse(cs.xml_doc([RAW_GT_ROW, CANCEL_ROW]))
        self.assertEqual(entries[0].text, "t")

    def test_raw_gt_row_survives_an_edit_and_save(self):
        path = _save(cs.xml_doc([RAW_GT_ROW, CANCEL_ROW]), _set(0, text="u"))
        cs.assert_xml_intact(self, path, ["a > b", "Cancel"])

    def test_strings_and_stringtable_elements_are_not_rows(self):
        other = ['    <strings>x</strings>\n', '    <stringTable name="T">y</stringTable>\n']
        _, _, entries = _parse(cs.xml_doc(other + [CANCEL_ROW]))
        self.assertEqual([e.name for e in entries], ["Cancel"])

    def test_data_name_attribute_is_not_read_as_the_name(self):
        _, _, entries = _parse(cs.xml_doc([DATA_NAME_ROW]))
        self.assertEqual(entries[0].name, "Save")

    def test_empty_row_keeps_its_row(self):
        path = _save(cs.xml_doc([EMPTY_ROW, CANCEL_ROW]))
        cs.assert_xml_intact(self, path, ["E", "Cancel"])

    def test_missing_attribute_is_added_when_edited(self):
        for field_name, value in (("translator", "Jane"), ("status", "Complete"),
                                  ("modify_date", cs.DEFAULT_DATE), ("istablet", "true")):
            with self.subTest(field=field_name):
                path = _save(cs.xml_doc([BARE_ROW]), _set(0, **{field_name: value}))
                self.assertEqual(getattr(xte.parse_file(path)[1][0], field_name), value)

    def test_missing_attribute_stays_missing_when_its_value_is_the_default(self):
        path = _save(cs.xml_doc([BARE_ROW]), _set(0, text="n"))
        self.assertIn('<string name="M">n</string>', path.read_text(encoding="utf-8"))



MULTI_ROWS = [cs.row("Save", "Saglabāt"), cs.row("Cancel", "Atcelt"), cs.row("Two", "line 1\nline 2")]
COMMENTED_HEADER = ('<?xml version="1.0" encoding="utf-8"?>\n<!-- exported -->\n<?app mode="x"?>\n'
                    '<TRNExportImportModel Culture="lv-LV">\n  <resources>\n')


class LineEndingTests(unittest.TestCase):
    def test_lf_file_saves_byte_identical(self):
        text = cs.xml_doc(MULTI_ROWS)
        self.assertEqual(_save(text).read_bytes(), text.encode("utf-8"))

    def test_crlf_file_saves_byte_identical(self):
        text = cs.xml_doc(MULTI_ROWS, newline="\r\n")
        self.assertEqual(_save(text).read_bytes(), text.encode("utf-8"))

    def test_bom_file_saves_byte_identical(self):
        text = cs.xml_doc(MULTI_ROWS, bom=True)
        self.assertEqual(_save(text).read_bytes(), text.encode("utf-8"))

    def test_comments_and_irregular_whitespace_save_byte_identical(self):
        rows = [cs.row("Save", "Saglabāt"), "\t<!-- between -->\n\n",
                "  " + cs.row("Cancel", "Atcelt").lstrip()]
        text = cs.xml_doc(rows, header=COMMENTED_HEADER)
        self.assertEqual(_save(text).read_bytes(), text.encode("utf-8"))

    def test_crlf_text_reads_with_lf_newlines(self):
        _, _, entries = _parse(cs.xml_doc(MULTI_ROWS, newline="\r\n"))
        self.assertEqual(entries[2].text, "line 1\nline 2")

    def test_edited_text_in_a_crlf_file_is_written_with_crlf(self):
        path = _save(cs.xml_doc(MULTI_ROWS, newline="\r\n"), _set(2, text="a\nb"))
        self.assertNotIn(b"\n", path.read_bytes().replace(b"\r\n", b""))

    def test_edited_text_in_an_lf_file_is_written_with_lf(self):
        path = _save(cs.xml_doc(MULTI_ROWS), _set(2, text="a\nb"))
        self.assertNotIn(b"\r", path.read_bytes())

    def test_second_save_is_byte_identical_to_the_first(self):
        path = _save(cs.xml_doc(MULTI_ROWS), _set(0, text="Jauns"))
        first = path.read_bytes()
        segments, entries, *_ = xte.parse_file(path)
        xte.save_file(path, segments, entries)
        self.assertEqual(path.read_bytes(), first)

    def test_merge_addition_in_a_crlf_file_is_written_with_crlf(self):
        path, segments, entries = _parse(cs.xml_doc(MULTI_ROWS, newline="\r\n"))
        new_segments, new_entries = xte.insert_additions(
            segments, entries, [cs.make_entry(name="New", text="Jauns\nteksts")])
        xte.save_file(path, new_segments, new_entries)
        self.assertNotIn(b"\n", path.read_bytes().replace(b"\r\n", b""))

    def test_merge_addition_in_an_lf_file_is_written_with_lf(self):
        path, segments, entries = _parse(cs.xml_doc(MULTI_ROWS))
        new_segments, new_entries = xte.insert_additions(
            segments, entries, [cs.make_entry(name="New", text="Jauns")])
        xte.save_file(path, new_segments, new_entries)
        self.assertNotIn(b"\r", path.read_bytes())



APOS_ROW = (f'    <string name="it&#x27;s" translator="Jane" status="Complete" '
            f'modifyDate="{cs.DEFAULT_DATE}" istablet="false">don&#x27;t</string>\n')
CDATA_ROW = (f'    <string name="C" translator="Jane" status="Complete" '
             f'modifyDate="{cs.DEFAULT_DATE}" istablet="false"><![CDATA[a<b & c]]></string>\n')


class UnchangedRowTests(unittest.TestCase):
    def test_frozen_sample_saves_byte_identical(self):
        original = (cs.DATA / "Latvian.xml").read_bytes()
        path = _save(original.decode("utf-8"), name="Latvian.xml")
        self.assertEqual(path.read_bytes(), original)

    def test_untouched_row_keeps_its_legacy_apostrophe_escape(self):
        text = cs.xml_doc([APOS_ROW, CANCEL_ROW])
        path = _save(text, _set(1, text="Atsaukt"))
        self.assertEqual(path.read_bytes(), text.replace(">Atcelt<", ">Atsaukt<").encode("utf-8"))

    def test_editing_one_row_of_the_sample_changes_only_that_line(self):
        original = (cs.DATA / "Latvian.xml").read_bytes().decode("utf-8")
        path, segments, entries = _parse(original, "Latvian.xml")
        entry = next(e for e in entries if e.text and "&" not in segments[e.seg_idx]
                     and "\n" not in segments[e.seg_idx])
        old_line = next(line for line in original.splitlines() if segments[entry.seg_idx] in line)
        new_line = old_line.replace(f">{entry.text}</string>", ">Jauns teksts</string>")
        entry.text = "Jauns teksts"
        xte.save_file(path, segments, entries)
        changed = [line for line in difflib.ndiff(original.splitlines(),
                                                  path.read_bytes().decode("utf-8").splitlines())
                   if line.startswith(("- ", "+ "))]
        self.assertEqual(changed, ["- " + old_line, "+ " + new_line])

    def test_cdata_row_survives_an_unchanged_save(self):
        text = cs.xml_doc([CDATA_ROW, CANCEL_ROW])
        self.assertEqual(_save(text).read_bytes(), text.encode("utf-8"))

    def test_cdata_text_is_read_literally(self):
        _, _, entries = _parse(cs.xml_doc([CDATA_ROW]))
        self.assertEqual(entries[0].text, "a<b & c")

    def test_edited_cdata_row_is_written_as_escaped_text(self):
        path = _save(cs.xml_doc([CDATA_ROW]), _set(0, text="new & <v>"))
        self.assertIn('istablet="false">new &amp; &lt;v&gt;</string>',
                      path.read_text(encoding="utf-8"))

    def test_edited_cdata_row_reads_back_the_new_value(self):
        path = _save(cs.xml_doc([CDATA_ROW]), _set(0, text="new & <v>"))
        self.assertEqual(xte.parse_file(path)[1][0].text, "new & <v>")



class AtomicSaveTests(unittest.TestCase):
    def _save_with_failing_replace(self) -> Tuple[Path, str, object]:
        """Edit and save with os.replace() failing; returns (path, original text, the error or None)."""
        text = cs.xml_doc(MULTI_ROWS)
        path, segments, entries = _parse(text)
        entries[0].text = "Changed"
        with mock.patch.object(os, "replace", side_effect=OSError("locked")):
            try:
                xte.save_file(path, segments, entries)
            except OSError as error:
                return path, text, error
        return path, text, None

    def test_failed_save_raises(self):
        _, _, error = self._save_with_failing_replace()
        self.assertIsInstance(error, OSError)

    def test_failed_save_leaves_the_original_intact(self):
        path, text, _ = self._save_with_failing_replace()
        self.assertEqual(path.read_bytes(), text.encode("utf-8"))

    def test_failed_save_leaves_no_temp_file(self):
        path, _, _ = self._save_with_failing_replace()
        self.assertEqual(list(path.parent.glob(".*.tmp")), [])

    def test_successful_save_leaves_no_temp_file(self):
        path = _save(cs.xml_doc(MULTI_ROWS), _set(0, text="Changed"))
        self.assertEqual(list(path.parent.glob(".*.tmp")), [])



THREE_ROWS = [cs.row("Save", "Saglabāt"), cs.row("Cancel", "Atcelt"), cs.row("Open", "Atvērt")]


class RemoveEntrySegmentTests(unittest.TestCase):
    def test_removing_any_row_leaves_no_blank_line(self):
        for index in range(3):
            for newline in ("\n", "\r\n"):
                with self.subTest(index=index, newline=repr(newline)):
                    _, segments, entries = _parse(cs.xml_doc(THREE_ROWS, newline=newline))
                    xte._remove_entry_segment(segments, entries[index].seg_idx)
                    remaining = THREE_ROWS[:index] + THREE_ROWS[index + 1:]
                    self.assertEqual("".join(segments), cs.xml_doc(remaining, newline=newline))

    def test_removing_two_adjacent_rows_leaves_no_blank_line(self):
        _, segments, entries = _parse(cs.xml_doc(THREE_ROWS))
        xte._remove_entry_segment(segments, entries[0].seg_idx)
        xte._remove_entry_segment(segments, entries[1].seg_idx)
        self.assertEqual("".join(segments), cs.xml_doc(THREE_ROWS[2:]))

    def test_other_rows_keep_their_seg_idx(self):
        _, segments, entries = _parse(cs.xml_doc(THREE_ROWS))
        xte._remove_entry_segment(segments, entries[1].seg_idx)
        self.assertEqual(xte._get_attr(segments[entries[2].seg_idx], "name"), "Open")


if __name__ == "__main__":
    sys.exit(cs.run_suite(sys.modules[__name__]))
