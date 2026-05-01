function Table(el)
    local keys = {}
    for k, v in pairs(el) do
        table.insert(keys, k .. "=" .. type(v))
    end
    io.stderr:write("Table fields: " .. table.concat(keys, ", ") .. "\n")
    io.stderr:write("widths type: " .. type(el.widths) .. "\n")
    io.stderr:write("aligns type: " .. type(el.aligns) .. "\n")
    return el
end
