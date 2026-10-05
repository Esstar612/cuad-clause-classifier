// Offsets are code points into the gold text (Python str indices); the browser selects in UTF-16 units.
function codePointOffset(text, utf16) {
  return Array.from(text.slice(0, utf16)).length;
}

function utf16Offsets(text) {
  const chars = Array.from(text);
  const out = new Int32Array(chars.length + 1);
  for (let i = 0; i < chars.length; i++) out[i + 1] = out[i] + chars[i].length;
  return out;
}

// measure(range) returns the UTF-16 length of the text before the range start, inside pre.
function selectionSpan(range, pre, text, measure) {
  if (!range || range.collapsed || !pre.contains(range.startContainer) || !pre.contains(range.endContainer)) {
    return null;
  }
  const s16 = measure(range);
  const e16 = s16 + range.toString().length;
  return [codePointOffset(text, s16), codePointOffset(text, e16)];
}

if (typeof module !== "undefined") module.exports = { codePointOffset, utf16Offsets, selectionSpan };
