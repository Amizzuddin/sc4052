-- fix-tables.lua
-- Force all table columns to have proportional widths so they fit the page width
-- Compatible with pandoc 2.9.x (uses widths/aligns/headers/rows Table structure)

function Table(el)
    local ncols = #el.widths
    if ncols > 0 then
        -- Assign equal fractional widths to all columns
        -- Using 0.95 to leave a small margin buffer and avoid overflow
        local width = 0.95 / ncols
        for i = 1, ncols do
            el.widths[i] = width
        end
    end
    return el
end
