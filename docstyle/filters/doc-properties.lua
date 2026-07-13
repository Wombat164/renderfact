-- doc-properties.lua -- native markdown syntax for a Word DOCPROPERTY field
-- reference: the visible half of custom document properties. The property's
-- actual name/type/value is declared centrally (template-profile.yaml
-- `custom_properties:`, read by docstyle/custom_properties.py, which writes
-- docProps/custom.xml and fills in the cached display text below AFTER this
-- filter runs) -- this filter only places the FIELD, it does not know the
-- value, so a template's `--template-profile` can change without touching
-- the source markdown at all.
--
--   Client: [ ]{.docproperty name="ClientName"}
--
-- Becomes a real w:fldSimple DOCPROPERTY field (RawInline("openxml", ...), the
-- same raw_attribute pass-through form-controls.lua uses for w:sdt controls),
-- with a guillemet placeholder («ClientName») as its cached result text until
-- docstyle/custom_properties.py fills in the real value -- or until Word
-- itself recalculates the field (F9 / update-fields-on-print), the same as
-- any other Word field whose cache has gone stale.
--
-- w:fldSimple (not the begin/separate/end run-split form) is deliberately the
-- simpler of the two ways Word represents a field: DOCPROPERTY has no nested
-- fields inside its own result, so the split form's only advantage (nesting)
-- buys nothing here.

local function xml_escape(s)
  return (s:gsub('&', '&amp;'):gsub('<', '&lt;'):gsub('>', '&gt;')
           :gsub('"', '&quot;'))
end

local function fail(msg)
  error('doc-properties.lua: ' .. msg, 0)
end

local function build_docproperty(span)
  local attrs = span.attributes
  local name = attrs.name
  if not name or name == '' then
    fail(".docproperty span requires a non-empty 'name' attribute")
  end
  if not name:match('^[%w_]+$') then
    fail(".docproperty name=\"" .. name .. "\" must be alphanumeric/underscore only "
      .. "(matches the custom_properties key it will bind to in --template-profile)")
  end
  local instr = ' DOCPROPERTY ' .. name .. ' \\* MERGEFORMAT '
  local placeholder = xml_escape('\194\171' .. name .. '\194\187')  -- «name» (U+00AB / U+00BB)
  return '<w:fldSimple w:instr="' .. xml_escape(instr) .. '">'
    .. '<w:r><w:t>' .. placeholder .. '</w:t></w:r></w:fldSimple>'
end

function Span(span)
  if span.classes:includes('docproperty') then
    return pandoc.RawInline('openxml', build_docproperty(span))
  end
  return nil
end
