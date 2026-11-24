-- Five persistent workspaces: an empty workspace stays visible in the bar instead of vanishing,
-- which is what makes the indicator readable.

for i = 1, 5 do
    hl.workspace_rule({ workspace = tostring(i), persistent = true })
end
