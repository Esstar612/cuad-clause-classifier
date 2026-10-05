// Run by tests/test_fresh.py when Node is installed.
const assert = require("assert");
const { codePointOffset, utf16Offsets, selectionSpan } = require("../tools/labeler/offsets.js");

const text = "Ab\u{1F600}c\r\ndéf";            // an astral character (2 UTF-16 units) and CRLF
assert.strictEqual(codePointOffset(text, 0), 0);
assert.strictEqual(codePointOffset(text, 4), 3);     // past the emoji: 4 units, 3 code points
assert.strictEqual(codePointOffset(text, text.length), Array.from(text).length);
const u16 = utf16Offsets(text);
for (let cp = 0; cp <= Array.from(text).length; cp++) assert.strictEqual(codePointOffset(text, u16[cp]), cp);

const inside = { id: "inside" }, outside = { id: "outside" };
const pre = { contains: (n) => n === inside };
const range = (s, e, extra = {}) => ({ startContainer: inside, endContainer: inside, collapsed: false,
                                       toString: () => text.slice(s, e), s, ...extra });
const measure = (r) => r.s;
assert.deepStrictEqual(selectionSpan(range(2, 5), pre, text, measure), [2, 4]);
assert.strictEqual(selectionSpan(range(2, 2, { collapsed: true }), pre, text, measure), null);
assert.strictEqual(selectionSpan(range(0, 3, { startContainer: outside }), pre, text, measure), null);
assert.strictEqual(selectionSpan(range(0, 3, { endContainer: outside }), pre, text, measure), null);
assert.strictEqual(selectionSpan(null, pre, text, measure), null);
console.log("ok");
