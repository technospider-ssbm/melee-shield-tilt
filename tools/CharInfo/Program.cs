using System.Text;
using System.Text.Json;
using HSDRaw;
using HSDRaw.Melee.Pl;
using HSDRaw.Common;
using HSDRaw.Common.Animation;

// Defaults assume the working directory is the repo root.
string gamedata = args.Length > 0 ? args[0] : "gamedata";
string outDir = args.Length > 1 ? args[1] : "data";
Directory.CreateDirectory(outDir);

// code -> descriptive name
var characters = new (string Code, string Name)[]
{
    ("Mr", "Mario"), ("Lg", "Luigi"), ("Pe", "Peach"), ("Kp", "Bowser"), ("Ys", "Yoshi"),
    ("Dk", "DonkeyKong"), ("Ca", "CaptainFalcon"), ("Gn", "Ganondorf"), ("Fc", "Falco"),
    ("Fx", "Fox"), ("Ns", "Ness"), ("Pp", "Popo"), ("Nn", "Nana"), ("Kb", "Kirby"),
    ("Ss", "Samus"), ("Zd", "Zelda"), ("Sk", "Sheik"), ("Lk", "Link"), ("Cl", "YoungLink"),
    ("Pk", "Pikachu"), ("Pc", "Pichu"), ("Pr", "Jigglypuff"), ("Mt", "Mewtwo"), ("Gw", "MrGameAndWatch"),
    ("Ms", "Marth"), ("Fe", "Roy"), ("Dr", "DrMario"),
};

var commonData = new Dictionary<string, object?>();
var charOut = new Dictionary<string, object?>();
var oddities = new List<string>();

// ---------- PlCo.dat ----------
{
    var path = Path.Combine(gamedata, "PlCo.dat");
    var file = new HSDRawFile(path);
    var root = file.Roots.FirstOrDefault(r => r.Data is HSDRaw.Melee.SBM_ftLoadCommonData);
    if (root == null)
    {
        Console.Error.WriteLine("PlCo.dat: could not find ftLoadCommonData root");
    }
    else
    {
        var common = (HSDRaw.Melee.SBM_ftLoadCommonData)root.Data;
        var attrs = common.CommonAttributes; // ftLoadCommandDataCommonAttributes @ 0x00, raw struct = ftCommonData
        var s = attrs._s;
        commonData["_root_symbol"] = root.Name;
        commonData["_struct_length_bytes"] = s.Length;
        commonData["x44C_tilt_easing_factor"] = s.GetFloat(0x44C);
        commonData["x260_start_shield_health"] = s.GetFloat(0x260);
        commonData["x264_min_shield_scale"] = s.GetFloat(0x264);
        commonData["x2D4_lightshield_range_min"] = s.GetFloat(0x2D4);
        commonData["x2D8_lightshield_range_max"] = s.GetFloat(0x2D8);
        // other guard-related fields identified in ftCo_Guard.c / fighter.c
        commonData["x27C_shield_regen_amount"] = s.GetFloat(0x27C);
        commonData["x280_unk_shield_health"] = s.GetFloat(0x280);
        commonData["x2A0_powershield_input_window_frames"] = s.GetInt32(0x2A0);
        commonData["x2F4_lightshield_alpha_base"] = s.GetFloat(0x2F4);
        commonData["x3E8_shield_knockback_frame_decay"] = s.GetFloat(0x3E8);
        commonData["x3EC_shield_ground_friction_multiplier"] = s.GetFloat(0x3EC);
        commonData["x68_guard_x24_init"] = s.GetFloat(0x68);

        // Bone lookup tables (per fighter-kind skeleton joint counts)
        var boneTables = common.BoneTables;
        if (boneTables != null)
        {
            var counts = new List<object>();
            for (int i = 0; i < boneTables.Length; i++)
            {
                var bt = boneTables[i];
                counts.Add(new Dictionary<string, object?> { ["kind_index"] = i, ["bone_count"] = bt?.BoneCount });
            }
            commonData["bone_tables_by_kind_index"] = counts;
            oddities.Add("PlCo.dat BoneTables[] gives a bone/joint count per internal fighter-kind index, " +
                "but the kind->character mapping was not independently confirmed (Ft_Kind enum order != extraction order). " +
                "Treat bone_tables_by_kind_index as indexed by internal kind id, not by the Code list below.");
        }
    }
}

// ---------- per character ----------
foreach (var (code, name) in characters)
{
    var datPath = Path.Combine(gamedata, $"Pl{code}.dat");
    var ajPath = Path.Combine(gamedata, $"Pl{code}AJ.dat");
    if (!File.Exists(datPath))
    {
        oddities.Add($"{code}: Pl{code}.dat missing, skipped");
        continue;
    }

    var file = new HSDRawFile(datPath);
    var root = file.Roots.FirstOrDefault(r => r.Data is SBM_FighterData);
    if (root == null)
    {
        oddities.Add($"{code}: no SBM_FighterData root found in Pl{code}.dat (roots: {string.Join(",", file.Roots.Select(r => r.Name))})");
        continue;
    }

    var fd = (SBM_FighterData)root.Data;
    var entry = new Dictionary<string, object?>();
    entry["root_symbol"] = root.Name;
    entry["root_type"] = root.Data.GetType().Name;

    // shield bone
    byte shieldBone = 255;
    try { shieldBone = fd.ModelLookupTables.ShieldBone; }
    catch (Exception e) { oddities.Add($"{code}: ModelLookupTables/ShieldBone read failed: {e.Message}"); }
    entry["shield_bone_index"] = shieldBone;
    entry["shield_bone_joint_name"] = null; // not stored in file; Melee dat JOBJs carry no names

    // initial shield size
    try { entry["initial_shield_size"] = fd.Attributes.ShieldSize; }
    catch (Exception e) { oddities.Add($"{code}: Attributes.ShieldSize read failed: {e.Message}"); }

    // shield pose container (FighterData + 0x20)
    try
    {
        var spc = fd.ShieldPoseContainer;
        if (spc == null)
        {
            entry["shield_pose_container"] = null;
            oddities.Add($"{code}: ShieldPoseContainer is null");
        }
        else
        {
            var pcInfo = new Dictionary<string, object?>();
            pcInfo["raw_struct_length_bytes"] = spc._s.Length;
            pcInfo["raw_pointer_count"] = spc._s.References.Count; // pointers stored directly in this struct
            var pose = spc.ShieldPose;
            pcInfo["shield_pose_jobj_present"] = pose != null;
            if (pose != null)
            {
                pcInfo["jobj_next_chain_count"] = pose.List.Count; // sibling(Next)-chain length starting at root
                int childCount = pose.Child?.List.Count ?? 0;
                pcInfo["root_child_count"] = childCount;
                pcInfo["total_joints_root_plus_children"] = 1 + childCount;
                pcInfo["note"] = "FighterData+0x20 (SBM_ShieldModelContainer) has exactly ONE pointer field " +
                    "(TrimmedSize=4) pointing to a single root JOBJ. The decomp runtime struct ftData_x20 " +
                    "{ HSD_Joint** x0; f32 x8; } is built at fighter-load time by flattening this JOBJ's tree " +
                    "(root + Child-list, depth-first) into a pointer array; x0[2] is therefore the 3rd joint in " +
                    "that flattened order (root=0, first child=1, second child=2), used by ftCo_80091E78 as the " +
                    "FtPart_TransN blend-target joint for the translucent/lightshield-fade shield model, NOT the " +
                    "shield bubble scale target (that is ModelLookupTables.ShieldBone applied to fp->parts[...] instead).";
            }
            entry["shield_pose_container"] = pcInfo;
        }
    }
    catch (Exception e)
    {
        oddities.Add($"{code}: ShieldPoseContainer parse failed: {e.Message}");
    }

    // hurtboxes
    try
    {
        var hb = fd.Hurtboxes;
        var arr = hb?.Hurtboxes;
        if (arr == null)
        {
            entry["hurtboxes"] = new List<object>();
        }
        else
        {
            var list = new List<object>();
            foreach (var h in arr)
            {
                list.Add(new Dictionary<string, object?>
                {
                    ["bone_index"] = h.BoneIndex,
                    ["joint_name"] = null, // not stored in file
                    ["type"] = h.Type.ToString(),
                    ["grabbable"] = h.Grabbable,
                    ["x1"] = h.X1, ["y1"] = h.Y1, ["z1"] = h.Z1,
                    ["x2"] = h.X2, ["y2"] = h.Y2, ["z2"] = h.Z2,
                    ["radius"] = h.Size,
                });
            }
            entry["hurtboxes"] = list;
            entry["hurtbox_count"] = list.Count;
            entry["hurtbox_max_bone_index"] = arr.Length == 0 ? -1 : arr.Max(h => h.BoneIndex);
        }
    }
    catch (Exception e)
    {
        oddities.Add($"{code}: Hurtboxes parse failed: {e.Message}");
    }

    // action table entries 36-42 + AJ resolution for #38
    try
    {
        var table = fd.FighterActionTable;
        var cmds = table.Commands;
        var actionsInfo = new Dictionary<string, object?>();
        var range = new List<object>();
        for (int i = 36; i <= 42 && i < cmds.Length; i++)
        {
            range.Add(new Dictionary<string, object?>
            {
                ["index"] = i,
                ["name"] = cmds[i].Name,
                ["animation_offset_in_AJ"] = cmds[i].AnimationOffset,
                ["animation_size_bytes"] = cmds[i].AnimationSize,
            });
        }
        actionsInfo["entries_36_to_42"] = range;
        actionsInfo["total_action_count"] = cmds.Length;

        if (38 < cmds.Length)
        {
            var e38 = cmds[38];
            actionsInfo["entry_38_name"] = e38.Name;
            actionsInfo["entry_38_animation_offset_in_AJ"] = e38.AnimationOffset;
            actionsInfo["entry_38_animation_size_bytes"] = e38.AnimationSize;

            bool looksLikeGuard = e38.Name != null && e38.Name.IndexOf("Guard", StringComparison.OrdinalIgnoreCase) >= 0;
            actionsInfo["entry_38_name_contains_guard"] = looksLikeGuard;
            if (!looksLikeGuard)
                oddities.Add($"{code}: action-table entry 38 name '{e38.Name}' does NOT contain 'Guard' as expected");

            // read frame count directly from the AJ file at the given raw byte offset
            if (File.Exists(ajPath) && e38.AnimationSize > 0)
            {
                var ajBytes = File.ReadAllBytes(ajPath);
                if (e38.AnimationOffset >= 0 && e38.AnimationOffset + e38.AnimationSize <= ajBytes.Length)
                {
                    var slice = new byte[e38.AnimationSize];
                    Array.Copy(ajBytes, e38.AnimationOffset, slice, 0, e38.AnimationSize);
                    try
                    {
                        var animFile = new HSDRawFile(slice);
                        var figaRoot = animFile.Roots.FirstOrDefault(r => r.Data is HSD_FigaTree);
                        if (figaRoot != null)
                        {
                            var tree = (HSD_FigaTree)figaRoot.Data;
                            actionsInfo["entry_38_anim_symbol"] = figaRoot.Name;
                            actionsInfo["entry_38_frame_count"] = tree.FrameCount;
                        }
                        else
                        {
                            oddities.Add($"{code}: entry 38 AJ slice did not parse to a FigaTree root (roots: {string.Join(",", animFile.Roots.Select(r => $"{r.Name}:{r.Data?.GetType().Name}"))})");
                        }
                    }
                    catch (Exception e2)
                    {
                        oddities.Add($"{code}: entry 38 AJ slice parse failed: {e2.Message}");
                    }
                }
                else
                {
                    oddities.Add($"{code}: entry 38 animation offset/size out of range of Pl{code}AJ.dat (offset=0x{e38.AnimationOffset:X}, size=0x{e38.AnimationSize:X}, file size=0x{ajBytes.Length:X})");
                }
            }
        }
        else
        {
            oddities.Add($"{code}: action table has only {cmds.Length} entries, index 38 out of range");
        }
        entry["actions"] = actionsInfo;
    }
    catch (Exception e)
    {
        oddities.Add($"{code}: FighterActionTable parse failed: {e.Message}");
    }

    charOut[code] = new Dictionary<string, object?> { ["name"] = name, ["data"] = entry };
}

var options = new JsonSerializerOptions { WriteIndented = true };

var commonOutPath = Path.Combine(outDir, "common.json");
File.WriteAllText(commonOutPath, JsonSerializer.Serialize(commonData, options));
Console.WriteLine($"wrote {commonOutPath}");

var charFinal = new Dictionary<string, object?>();
foreach (var kv in charOut)
{
    var d = (Dictionary<string, object?>)kv.Value!;
    var data = (Dictionary<string, object?>)d["data"]!;
    data["name"] = d["name"];
    charFinal[kv.Key] = data;
}
var charOutPath = Path.Combine(outDir, "characters.json");
File.WriteAllText(charOutPath, JsonSerializer.Serialize(charFinal, options));
Console.WriteLine($"wrote {charOutPath}");

var odditiesPath = Path.Combine(outDir, "extract_oddities.json");
File.WriteAllText(odditiesPath, JsonSerializer.Serialize(oddities, options));
Console.WriteLine($"wrote {odditiesPath} ({oddities.Count} entries)");
