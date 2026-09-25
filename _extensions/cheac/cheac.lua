-- {{< cheac >}} inserts the CHEAC wordmark inline, scaled to the surrounding text.
local function wordmark_path(ext)
  local offset = quarto.project.offset or "."
  return offset .. "/assets/logos/cheac-wordmark." .. ext
end

return {
  ["cheac"] = function(args, kwargs, meta)
    if quarto.doc.is_format("latex") then
      return pandoc.RawInline("latex",
        "\\raisebox{-0.12em}{\\includegraphics[height=0.8em]{" .. wordmark_path("pdf") .. "}}")
    elseif quarto.doc.is_format("html") then
      return pandoc.RawInline("html",
        '<img src="' .. wordmark_path("svg") .. '" alt="CHEAC" class="cheac-wordmark">')
    end
    return pandoc.Str("CHEAC")
  end
}
