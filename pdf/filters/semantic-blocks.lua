-- semantic-blocks.lua -- map renderfact's first-class semantic blocks to typst
-- function calls (issue #33). Runs during `pandoc <md> -t typst`.
--
-- A fenced div with a known class becomes a RawBlock("typst", "#<fn>(...)")
-- rendered by the active theme's pdf/theme/blocks.typ. Each block reads a simple
-- bullet list of pipe-delimited fields, so the source stays plain markdown:
--
--   ::: signatures            ::: attendance              ::: statement
--   - Name | Role             - present | Who             - heading | Ontvangsten
--   - Name | Role             - proxy | Who (via X)       - item | Bijdragen | 8.045,77
--   :::                       - quorum | 3/5, bereikt     - rule
--                             :::                         - total | Saldo | 1.510,53
--                                                         :::
--
-- Domain-generic across meeting minutes and financial reports; the styling lives
-- in the theme, not here.

local function typ_str(s)
  return '"' .. s:gsub('\\', '\\\\'):gsub('"', '\\"') .. '"'
end

local function trim(s)
  return (s:gsub('^%s+', ''):gsub('%s+$', ''))
end

-- split "a | b | c" -> {"a","b","c"} (trimmed; empty trailing fields kept as "")
local function split_pipe(s)
  local parts = {}
  for part in (s .. '|'):gmatch('([^|]*)|') do
    parts[#parts + 1] = trim(part)
  end
  return parts
end

-- the stringified lines of the first bullet list inside the div
local function list_lines(div)
  local lines = {}
  for _, block in ipairs(div.content) do
    if block.t == 'BulletList' then
      for _, item in ipairs(block.content) do
        lines[#lines + 1] = trim(pandoc.utils.stringify(item))
      end
      break
    end
  end
  return lines
end

local function signatures(div)
  local cards = {}
  for _, line in ipairs(list_lines(div)) do
    local p = split_pipe(line)
    cards[#cards + 1] = '(' .. typ_str(p[1] or '') .. ', ' .. typ_str(p[2] or '') .. ')'
  end
  return '#signatures((' .. table.concat(cards, ', ') .. ',))'
end

local function attendance(div)
  local entries = {}
  for _, line in ipairs(list_lines(div)) do
    local p = split_pipe(line)
    entries[#entries + 1] = '(kind: ' .. typ_str(p[1] or '') .. ', text: ' .. typ_str(p[2] or '') .. ')'
  end
  return '#attendance((' .. table.concat(entries, ', ') .. ',))'
end

local function statement(div)
  local rows = {}
  for _, line in ipairs(list_lines(div)) do
    local p = split_pipe(line)
    rows[#rows + 1] = '(kind: ' .. typ_str(p[1] or 'item')
      .. ', label: ' .. typ_str(p[2] or '')
      .. ', amount: ' .. typ_str(p[3] or '') .. ')'
  end
  return '#statement((' .. table.concat(rows, ', ') .. ',))'
end

local HANDLERS = { signatures = signatures, attendance = attendance, statement = statement }

function Div(div)
  for class, handler in pairs(HANDLERS) do
    if div.classes:includes(class) then
      return pandoc.RawBlock('typst', handler(div))
    end
  end
  return nil
end
