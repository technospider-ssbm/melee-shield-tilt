// --export-web: a compact JSON with everything tools/plots/shieldpose.js needs to reproduce
// FighterModel.LivePose / World / Sweep.Eval / hurtbox posing in the browser.
//
// Only joints on the shield chain and on hurtbox chains are exported (every ancestor of a kept joint is
// kept, so the subset is closed under "parent" and stays in preorder). Indices are remapped.
// Floats are written with the shortest round-trip float32 representation; the JS side applies Math.fround.
using System.Globalization;
using System.Text;

namespace ShieldPose;

public static class WebExport
{
    const uint JOBJ_CLASSICAL_SCALE = 1 << 3;

    static string F(float v) => v.ToString("R", CultureInfo.InvariantCulture);

    static void Srt9(StringBuilder sb, Srt s)
    {
        sb.Append(F(s.R.X)).Append(',').Append(F(s.R.Y)).Append(',').Append(F(s.R.Z)).Append(',')
          .Append(F(s.S.X)).Append(',').Append(F(s.S.Y)).Append(',').Append(F(s.S.Z)).Append(',')
          .Append(F(s.T.X)).Append(',').Append(F(s.T.Y)).Append(',').Append(F(s.T.Z));
    }

    static string Js(string s) => System.Text.Json.JsonSerializer.Serialize(s);

    public static void Write(IEnumerable<string> codes, string gamedata, CommonData c, string path)
    {
        var sb = new StringBuilder();
        sb.Append("{\"format\":\"shieldpose-web-1\",");
        sb.Append("\"common\":{");
        sb.Append("\"deadzone_x\":").Append(F(c.StickDeadzoneX)).Append(',');
        sb.Append("\"deadzone_y\":").Append(F(c.StickDeadzoneY)).Append(',');
        sb.Append("\"x260\":").Append(F(c.StartShieldHealth)).Append(',');
        sb.Append("\"x264\":").Append(F(c.MinScaleFrac)).Append(',');
        sb.Append("\"x2D4\":").Append(F(c.LightMin)).Append(',');
        sb.Append("\"x2D8\":").Append(F(c.LightMax)).Append("},");
        sb.Append("\"joint_fields\":\"parent,flags(1=classical_scale,2=item_hold,4=dynamics_b0,8=flags_b4),rest[rx,ry,rz,sx,sy,sz,tx,ty,tz],sp[9],tracks[[type,startframe,frac_value,frac_slope,length,base64]]\",");
        sb.Append("\"hurtbox_fields\":\"joint,part,type,grabbable,x1,y1,z1,x2,y2,z2,radius\",");
        sb.Append("\"chars\":{");
        bool firstChar = true;
        foreach (var code in codes)
        {
            FighterModel fm;
            try { fm = FighterModel.Load(gamedata, code, c); }
            catch (Exception e) { Console.Error.WriteLine($"[{code}] LOAD FAILED: {e.Message}"); continue; }

            var keep = fm.RelevantJoints();
            keep.Add(0);
            var order = keep.OrderBy(j => j).ToList();       // preorder indices ascending == preorder
            var remap = new Dictionary<int, int>();
            for (int i = 0; i < order.Count; i++) remap[order[i]] = i;

            if (!firstChar) sb.Append(',');
            firstChar = false;
            sb.Append(Js(code)).Append(":{");
            sb.Append("\"name\":").Append(Js(fm.Name)).Append(',');
            sb.Append("\"kind\":").Append(fm.Kind).Append(',');
            sb.Append("\"has_tilt\":").Append(fm.HasTilt ? "true" : "false").Append(',');
            sb.Append("\"end_frame\":").Append(F(fm.FrameCount)).Append(',');
            sb.Append("\"model_scale\":").Append(F(fm.ModelScale)).Append(',');
            sb.Append("\"shield_size\":").Append(F(fm.ShieldSize)).Append(',');
            sb.Append("\"shield_joint\":").Append(remap[fm.ShieldJoint]).Append(',');
            sb.Append("\"source_joints\":").Append(fm.Joints.Count).Append(',');
            if (code == "Nn")
                sb.Append("\"note\":").Append(Js("Nana: same bubble data as Popo (Guard figatree from PlPpAJ.dat, ftData_80085FD4); the explorer skips her.")).Append(',');
            if (!fm.HasTilt)
                sb.Append("\"tilt_note\":").Append(Js("No tilt: GuardHold uses the costume rest pose; bubble scale is the constant initial_shield_size.")).Append(',');
            sb.Append("\"joints\":[");
            for (int i = 0; i < order.Count; i++)
            {
                var ji = fm.Joints[order[i]];
                int flags = ((ji.Flags & JOBJ_CLASSICAL_SCALE) != 0 ? 1 : 0)
                          | (order[i] >= 1 && ji.Part == fm.ItemHoldPart ? 2 : 0)
                          | (fm.DynamicParts.Contains(ji.Part) ? 4 : 0)
                          | (fm.B4Parts.Contains(ji.Part) ? 8 : 0);
                if (i > 0) sb.Append(',');
                sb.Append('[').Append(ji.Parent < 0 ? -1 : remap[ji.Parent]).Append(',').Append(flags).Append(",[");
                Srt9(sb, ji.Rest);
                sb.Append("],[");
                Srt9(sb, ji.Sp);
                sb.Append("],[");
                for (int t = 0; t < ji.Tracks.Count; t++)
                {
                    var tr = ji.Tracks[t];
                    if (t > 0) sb.Append(',');
                    sb.Append('[').Append(tr.Type).Append(',').Append(tr.StartFrame).Append(',').Append(tr.FracValue).Append(',')
                      .Append(tr.FracSlope).Append(',').Append(tr.Length).Append(",\"").Append(Convert.ToBase64String(tr.Data)).Append("\"]");
                }
                sb.Append("]]");
            }
            sb.Append("],\"hurtboxes\":[");
            for (int h = 0; h < fm.Hurtboxes.Count; h++)
            {
                var hb = fm.Hurtboxes[h];
                if (h > 0) sb.Append(',');
                sb.Append('[').Append(hb.Joint < 0 ? -1 : remap[hb.Joint]).Append(',').Append(hb.Part).Append(',').Append(hb.Type).Append(',').Append(hb.Grab).Append(',')
                  .Append(F(hb.A.X)).Append(',').Append(F(hb.A.Y)).Append(',').Append(F(hb.A.Z)).Append(',')
                  .Append(F(hb.B.X)).Append(',').Append(F(hb.B.Y)).Append(',').Append(F(hb.B.Z)).Append(',').Append(F(hb.R)).Append(']');
            }
            sb.Append("],\"notes\":[").Append(string.Join(",", fm.Notes.Select(Js))).Append("]}");
            Console.WriteLine($"[{code}] {fm.Name}: {order.Count}/{fm.Joints.Count} joints, {order.Sum(j => fm.Joints[j].Tracks.Count)} tracks");
        }
        sb.Append("}}");
        File.WriteAllText(path, sb.ToString());
        Console.WriteLine($"wrote {path} ({new FileInfo(path).Length / 1024.0:0.0} KiB)");
    }
}
