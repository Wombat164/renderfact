-- form-controls.lua -- native markdown syntax for Word content controls (issue
-- #105, the follow-up C10 named: dropdown lists and checkboxes, the two gaps
-- the raw `{=openxml}` escape hatch (#96) never closed with real syntax).
--
-- Uses pandoc's own bracketed-span syntax (`native_spans`/`bracketed_spans`,
-- both on by default -- verified via `pandoc --list-extensions=markdown`, no
-- new reader extension to pin):
--
--   Choose your department: [ ]{.dropdown tag="dept" choices="IT|HR|Finance"}
--   Choose your department: [ ]{.dropdown tag="dept" choices="IT|HR|Finance" default="HR"}
--   I agree to the terms [ ]{.checkbox tag="agree"}
--   I agree to the terms [ ]{.checkbox tag="agree" checked="true"}
--
-- A matching span becomes a RawInline("openxml", "<w:sdt>...") -- the same
-- pass-through mechanism the manual escape hatch uses (pandoc_markdown.py's
-- pinned `raw_attribute`), so the docx writer splices the hand-built OOXML
-- verbatim into word/document.xml. No python-docx/lxml post-processing is
-- needed: w:dropDownList lives entirely in the already-declared `w:`
-- namespace, and w14:checkbox declares its own `xmlns:w14` locally on the
-- element (valid, self-contained XML -- does not require the document root,
-- which pandoc's own reference docx does NOT declare by default, to carry it).
--
-- w14:checkbox (modern SDT content control) was chosen over legacy
-- FORMCHECKBOX: the latter only toggles under Word's "restrict editing / fill
-- in forms" protection lock, which this generator does not turn on by
-- default; w14:checkbox is clickable in an unprotected document and shares
-- the same w:sdt scaffolding as the dropdown, so both features are one
-- builder engine, not two unrelated mechanisms. See docs/DECISIONS.md.
--
-- w:id must be unique per SDT in the document (ECMA-376 best practice, not a
-- hard Word requirement, but real Word always assigns one). A module-level
-- counter starting well above anything pandoc auto-assigns (e.g. its own ToC
-- SDT) keeps collisions practically impossible while staying fully
-- deterministic: same source markdown, same filter, same id sequence, every
-- run -- required for render-pipeline idempotency, so no math.random() or
-- os.time() anywhere in this file.

local checkbox_font = "MS Gothic"

local _next_id_value = 900000000
local function next_id()
  _next_id_value = _next_id_value + 1
  return _next_id_value
end

local function xml_escape(s)
  return (s:gsub('&', '&amp;'):gsub('<', '&lt;'):gsub('>', '&gt;')
           :gsub('"', '&quot;'))
end

-- split "a|b|c" -> {"a","b","c"}, trimmed, empty entries dropped
local function split_choices(s)
  local out = {}
  for part in (s .. '|'):gmatch('([^|]*)|') do
    local trimmed = part:gsub('^%s+', ''):gsub('%s+$', '')
    if trimmed ~= '' then out[#out + 1] = trimmed end
  end
  return out
end

-- error() (not os.exit): pandoc catches a Lua filter error, reports it with a
-- traceback, and exits non-zero on its own -- the idiomatic fatal path for a
-- pandoc filter, so a malformed control halts the render loudly instead of
-- leaving plain, unconverted text as a silent footgun.
local function fail(msg)
  error('form-controls.lua: ' .. msg, 0)
end

local function build_dropdown(span)
  local attrs = span.attributes
  local tag = attrs.tag
  if not tag or tag == '' then
    fail(".dropdown span requires a non-empty 'tag' attribute")
  end
  local choices_raw = attrs.choices
  if not choices_raw or choices_raw == '' then
    fail(".dropdown tag=\"" .. tag .. "\" requires a non-empty 'choices' attribute (pipe-delimited, e.g. choices=\"IT|HR|Finance\")")
  end
  local choices = split_choices(choices_raw)
  if #choices == 0 then
    fail(".dropdown tag=\"" .. tag .. "\" 'choices' attribute produced no items after parsing: \"" .. choices_raw .. "\"")
  end
  local default = attrs.default
  local default_idx = 1
  if default and default ~= '' then
    local found = false
    for i, c in ipairs(choices) do
      if c == default then default_idx = i; found = true; break end
    end
    if not found then
      fail(".dropdown tag=\"" .. tag .. "\" default=\"" .. default .. "\" is not one of the listed choices: \"" .. choices_raw .. "\"")
    end
  end
  local alias = attrs.alias
  if not alias or alias == '' then alias = tag end

  local items = {}
  for _, c in ipairs(choices) do
    local esc = xml_escape(c)
    items[#items + 1] = '<w:listItem w:displayText="' .. esc .. '" w:value="' .. esc .. '"/>'
  end
  local display = xml_escape(choices[default_idx])
  local id = next_id()

  return '<w:sdt><w:sdtPr>'
    .. '<w:alias w:val="' .. xml_escape(alias) .. '"/>'
    .. '<w:tag w:val="' .. xml_escape(tag) .. '"/>'
    .. '<w:id w:val="' .. id .. '"/>'
    .. '<w:dropDownList>' .. table.concat(items) .. '</w:dropDownList>'
    .. '</w:sdtPr><w:sdtContent><w:r><w:t xml:space="preserve">' .. display .. '</w:t></w:r></w:sdtContent></w:sdt>'
end

local function build_checkbox(span)
  local attrs = span.attributes
  local tag = attrs.tag
  if not tag or tag == '' then
    fail(".checkbox span requires a non-empty 'tag' attribute")
  end
  local alias = attrs.alias
  if not alias or alias == '' then alias = tag end
  local checked_attr = attrs.checked
  if checked_attr and checked_attr ~= 'true' and checked_attr ~= 'false' then
    fail(".checkbox tag=\"" .. tag .. "\" checked=\"" .. checked_attr .. "\" must be \"true\" or \"false\"")
  end
  local checked = checked_attr == 'true'
  local id = next_id()
  local val = checked and '1' or '0'
  -- 2612 BALLOT BOX WITH X / 2610 BALLOT BOX, MS Gothic -- the glyph codes
  -- real Word writes for a w14:checkbox content control.
  local glyph = checked and '\226\152\146' or '\226\152\144'

  return '<w:sdt><w:sdtPr>'
    .. '<w:alias w:val="' .. xml_escape(alias) .. '"/>'
    .. '<w:tag w:val="' .. xml_escape(tag) .. '"/>'
    .. '<w:id w:val="' .. id .. '"/>'
    .. '<w14:checkbox xmlns:w14="http://schemas.microsoft.com/office/word/2010/wordml">'
    .. '<w14:checked w14:val="' .. val .. '"/>'
    .. '<w14:checkedState w14:val="2612" w14:font="' .. checkbox_font .. '"/>'
    .. '<w14:uncheckedState w14:val="2610" w14:font="' .. checkbox_font .. '"/>'
    .. '</w14:checkbox>'
    .. '</w:sdtPr><w:sdtContent><w:r><w:rPr><w:rFonts w:ascii="' .. checkbox_font .. '" w:hAnsi="' .. checkbox_font .. '" w:hint="eastAsia"/></w:rPr><w:t>' .. glyph .. '</w:t></w:r></w:sdtContent></w:sdt>'
end

function Span(span)
  if span.classes:includes('dropdown') then
    return pandoc.RawInline('openxml', build_dropdown(span))
  end
  if span.classes:includes('checkbox') then
    return pandoc.RawInline('openxml', build_checkbox(span))
  end
  return nil
end
