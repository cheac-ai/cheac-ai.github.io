-- Sets date-modified to the date of the last git commit that touched the page,
-- so each page shows when its content last changed. Pages that set
-- date-modified themselves, and files git does not know yet, are left alone.
function Meta(meta)
  if meta["date-modified"] ~= nil then
    return meta
  end
  local file = quarto.doc.input_file
  local dir = pandoc.path.directory(file)
  local ok, out = pcall(pandoc.pipe, "git",
    { "-C", dir, "log", "-1", "--format=%cs", "--", pandoc.path.filename(file) }, "")
  local date = ok and out:match("^%s*(%d%d%d%d%-%d%d%-%d%d)") or nil
  if date then
    local months = { "Jan", "Feb", "Mar", "Apr", "May", "Jun",
                     "Jul", "Aug", "Sep", "Oct", "Nov", "Dec" }
    local y, m, d = date:match("(%d+)-(%d+)-(%d+)")
    meta["date-modified"] = pandoc.MetaString(
      string.format("%d %s %s", tonumber(d), months[tonumber(m)], y))
  end
  return meta
end
