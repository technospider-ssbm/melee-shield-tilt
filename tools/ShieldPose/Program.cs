using System.Globalization;
using System.Text;
using System.Text.Json;
using ShieldPose;

// Usage (run from the repo root; all paths are repo-relative):
//   dotnet run -c Release --project tools/ShieldPose                       -> all characters
//   dotnet run -c Release --project tools/ShieldPose -- --char Fx Ms       -> selected characters
//   dotnet run -c Release --project tools/ShieldPose -- --pose-dump --char Fx --angle 90 --mag 1 [--facing -1] [--out file.csv]
//   dotnet run -c Release --project tools/ShieldPose -- --export-web [--out data/shieldpose_web.json] [--char ...]
//   options: --gamedata <dir> (default gamedata)  --data <dir> (default data)  --no-hurtboxes  --sanity
CultureInfo.DefaultThreadCurrentCulture = CultureInfo.InvariantCulture;
Thread.CurrentThread.CurrentCulture = CultureInfo.InvariantCulture;

string gamedata = "gamedata", dataDir = "data";
var codes = new List<string>();
bool exportWeb = false, poseDump = false, noHurt = false, sanityOnly = false, selfTest = false;
float dumpAngle = 0, dumpMag = 1;
int dumpFacing = 1;
string? dumpOut = null;
for (int i = 0; i < args.Length; i++)
{
    switch (args[i])
    {
        case "--gamedata": gamedata = args[++i]; break;
        case "--data": dataDir = args[++i]; break;
        case "--char":
            while (i + 1 < args.Length && !args[i + 1].StartsWith("--")) codes.Add(args[++i]);
            break;
        case "--pose-dump": poseDump = true; break;
        case "--export-web": exportWeb = true; break;
        case "--angle": dumpAngle = float.Parse(args[++i], CultureInfo.InvariantCulture); break;
        case "--mag": dumpMag = float.Parse(args[++i], CultureInfo.InvariantCulture); break;
        case "--facing": dumpFacing = int.Parse(args[++i]); break;
        case "--out": dumpOut = args[++i]; break;
        case "--no-hurtboxes": noHurt = true; break;
        case "--sanity": sanityOnly = true; break;
        case "--selftest": selfTest = true; break;
        default: Console.Error.WriteLine($"unknown argument {args[i]}"); return 2;
    }
}
if (codes.Count == 0) codes = CharTable.All.Select(c => c.Code).ToList();

var common = CommonData.Load(Path.Combine(gamedata, "PlCo.dat"));
Directory.CreateDirectory(dataDir);

if (exportWeb)
{
    WebExport.Write(codes, gamedata, common, dumpOut ?? Path.Combine(dataDir, "shieldpose_web.json"));
    return 0;
}

if (poseDump)
{
    var fm = FighterModel.Load(gamedata, codes[0], common);
    var path = dumpOut ?? $"{fm.Code}_posedump_{dumpAngle.ToString(CultureInfo.InvariantCulture)}_{dumpMag.ToString(CultureInfo.InvariantCulture)}.csv";
    Sweep.PoseDump(fm, common, dumpAngle, dumpMag, dumpFacing, path);
    Console.WriteLine($"wrote {path}");
    return 0;
}

if (selfTest)
{
    // Cross-check the fobj.c port against HSDLib's independent FOBJ_Player (HSDRaw.Tools) on every
    // Guard-figatree track, frames 10..370 step 0.25. Small differences are expected only from HSDLib's
    // own float formulation; large ones would indicate a port bug.
    double worst = 0; string where = "";
    foreach (var code in codes)
    {
        FighterModel fm;
        try { fm = FighterModel.Load(gamedata, code, common); } catch { continue; }
        foreach (var j in fm.Joints)
            foreach (var t in j.Tracks)
            {
                var desc = new HSDRaw.Common.Animation.HSD_FOBJ();
                desc._s.SetByte(0x00, t.Type); desc._s.SetByte(0x01, t.FracValue); desc._s.SetByte(0x02, t.FracSlope);
                desc.Buffer = t.Data;
                var player = new HSDRaw.Tools.FOBJ_Player(desc);
                foreach (var k in player.Keys) k.Frame -= t.StartFrame;
                for (float f = 10; f <= 370; f += 0.25f)
                {
                    var mine = FObjInterp.Evaluate(t, f, fm.FrameCount);
                    if (mine is not float v) continue;
                    double d = Math.Abs(v - player.GetValue(f));
                    if (d > worst) { worst = d; where = $"{code} joint {j.Index} track {t.Type} frame {f}: port {v} hsdlib {player.GetValue(f)}"; }
                }
            }
    }
    Console.WriteLine($"selftest FObj port vs HSDLib FOBJ_Player: max |diff| = {worst:E3} ({where})");
    return worst < 1e-3 ? 0 : 1;
}

int failures = 0;
var summary = new List<string>();
foreach (var code in codes)
{
    FighterModel fm;
    try { fm = FighterModel.Load(gamedata, code, common); }
    catch (Exception e)
    {
        Console.Error.WriteLine($"[{code}] LOAD FAILED: {e.Message}");
        summary.Add($"{code}\tLOAD FAILED\t{e.Message}");
        failures++;
        continue;
    }
    if (sanityOnly) { Sweep.Sanity(fm, common); continue; }
    var sw = System.Diagnostics.Stopwatch.StartNew();
    var res = Sweep.Run(fm, common, dataDir, !noHurt);
    Console.WriteLine($"[{code}] {fm.Name}: {res.GridCount} grid (+{res.Grid370Rows} frame-370 rows) + {res.PolarCount} polar samples, checks {(res.ChecksPass ? "PASS" : "FAIL")}, {sw.ElapsedMilliseconds} ms");
    foreach (var n in fm.Notes) Console.WriteLine($"    note: {n}");
    if (!res.ChecksPass) failures++;
    summary.Add($"{code}\t{(res.ChecksPass ? "ok" : "CHECK FAIL")}\t{string.Join("; ", fm.Notes)}");
    if (code is "Fx" or "Ms" or "Kb") Sweep.Sanity(fm, common);
}
Console.WriteLine();
foreach (var s in summary) Console.WriteLine(s);
return failures == 0 ? 0 : 1;

namespace ShieldPose
{
    public sealed class RunResult
    {
        public int GridCount, PolarCount, Grid370Rows;
        public bool ChecksPass;
    }

    public static class Sweep
    {
        static string F(float v) => v.ToString("R", CultureInfo.InvariantCulture);
        static string F(double v) => ((float)v).ToString("R", CultureInfo.InvariantCulture);

        // ------------------------------------------------------------------ stick model (MECHANICS section 5)

        /// <summary>HSD_PadClampCheck3(x, y, shift=1, min=0, max=80), controller.c:171-191.</summary>
        static (sbyte, sbyte) Clamp(sbyte x, sbyte y)
        {
            const float max = 80, min = 0;
            float r = MathF.Sqrt(((float)x * (float)x) + ((float)y * (float)y));
            if (r < min) return (0, 0);
            if (r > max)
            {
                x = (sbyte)(((float)x * max) / r);
                y = (sbyte)(((float)y * max) / r);
                r = MathF.Sqrt(((float)x * (float)x) + ((float)y * (float)y));
            }
            if (r > 1.000000013351432e-10f)
            {
                x = (sbyte)((float)x - (((float)x * min) / r));
                y = (sbyte)((float)y - (((float)y * min) / r));
            }
            return (x, y);
        }

        /// <summary>Every (kx, ky) that can reach fp->input.lstick[0] (post clamp, /80, per-axis deadzone).</summary>
        public static List<(int Kx, int Ky, float Lx, float Ly)> StickGrid(CommonData c)
        {
            var set = new SortedSet<(int, int)>();
            for (int rx = -128; rx <= 127; rx++)
                for (int ry = -128; ry <= 127; ry++)
                {
                    var (x, y) = Clamp((sbyte)rx, (sbyte)ry);
                    float nx = (float)x / 80f, ny = (float)y / 80f;
                    int kx = MathF.Abs(nx) <= c.StickDeadzoneX ? 0 : x;
                    int ky = MathF.Abs(ny) <= c.StickDeadzoneY ? 0 : y;
                    set.Add((kx, ky));
                }
            return set.Select(p => (p.Item1, p.Item2, (float)p.Item1 / 80f, (float)p.Item2 / 80f)).ToList();
        }

        /// <summary>Settled (deg, x4) for a held stick (ftCo_80091BC4, ftCo_Guard.c:130-175; MECHANICS 1.1).</summary>
        public static (float Deg, float Mag) Settled(float lx, float ly, int facing)
        {
            float rad = F32.LbAtan2(ly, lx * facing);
            if (rad < 0) rad += 2 * (float)Math.PI;
            float deg = rad * 57.29577951f;
            if (deg < 0) deg = 0;
            if (deg > 359) deg = 359;
            float mag = MathF.Sqrt(lx * lx + ly * ly);
            if (mag > 1) mag = 1;
            return (deg, mag);
        }

        /// <summary>Iterates the x8 update of ftCo_80091BC4 (ftCo_Guard.c:130-162) in f32 with K = 0.5.</summary>
        public static float SimulateX8(float x8, float lx, float ly, int facing, int frames)
        {
            for (int i = 0; i < frames; i++)
            {
                float rad = F32.LbAtan2(ly, lx * facing);
                if (rad < 0) rad += 2 * (float)Math.PI;
                float deg = rad * 57.29577951f;
                if (deg < 0) deg = 0;
                if (deg > 359) deg = 359;
                float g = x8 - 10;
                float d = deg - g;
                if (d > 180) d -= 360; else if (d < -180) d += 360;
                float sm = d * 0.5f + g;
                if (sm > 360) { g = sm; g -= 360; }
                else { g = sm; if (g < 0) g += 360; }
                x8 = 10 + g;
            }
            return x8;
        }

        /// <summary>Angle in degrees (any real) -> tilt frame x8 = 10 + clamp(wrap(angle), 0, 359).</summary>
        public static float FrameForAngle(float angle)
        {
            float a = angle % 360f;
            if (a < 0) a += 360f;
            if (a > 359) a = 359;
            return 10f + a;
        }

        // ------------------------------------------------------------------ sample evaluation

        public sealed class Sample
        {
            public Mtx[] W = Array.Empty<Mtx>();
            public Vec3f Bubble;
            public float RadiusFull, RadiusMin;
            public double ChainSvMax, ChainSvMin;   // singular values of the shield bone's parent world matrix
        }

        public static Sample Eval(FighterModel fm, CommonData c, float frame, float m, int facing)
        {
            float bFull = fm.BubbleScale(c, c.StartShieldHealth, 1.0f);   // hard (digital) shield, full health
            float bMin = fm.BubbleScale(c, 0.0f, 1.0f);                     // health -> 0 limit (0.15 * size)
            var live = fm.LivePose(frame, m);
            var w = fm.World(live, facing, bFull);
            var sm = w[fm.ShieldJoint];
            int par = fm.Joints[fm.ShieldJoint].Parent;
            double chain = Math.Cbrt(Math.Abs(F32.Det3(w[par])));
            var sv = F32.SingularValues(w[par]);
            return new Sample
            {
                ChainSvMax = sv.Max,
                ChainSvMin = sv.Min,
                W = w,
                Bubble = new Vec3f(sm[0, 3] - w[0][0, 3], sm[1, 3] - w[0][1, 3], sm[2, 3] - w[0][2, 3]),
                RadiusFull = (float)(bFull * chain),
                RadiusMin = (float)(bMin * chain),
            };
        }

        static double Dist(Vec3f a, Vec3f b) =>
            Math.Sqrt(Math.Pow(a.X - b.X, 2) + Math.Pow(a.Y - b.Y, 2) + Math.Pow(a.Z - b.Z, 2));

        // ------------------------------------------------------------------ main sweep

        public static RunResult Run(FighterModel fm, CommonData c, string dataDir, bool hurt)
        {
            var res = new RunResult();
            var inv = CultureInfo.InvariantCulture;
            var grid = StickGrid(c);
            var csv = new StringBuilder();
            csv.AppendLine("sweep,stick_x,stick_y,angle,mag,bone_x,bone_y,bone_z,shield_radius_full,shield_radius_min");
            var hcsv = new StringBuilder();
            hcsv.AppendLine("sweep,stick_x,stick_y,angle,mag,hurtbox,part,joint,type,grabbable,x1,y1,z1,x2,y2,z2,radius");
            double maxAniso = 0;
            double shAniso = 0, shSvMax = 0, shSvMin = double.MaxValue;
            float rMinSeen = float.MaxValue, rMaxSeen = 0;
            void Track(Sample s)
            {
                shAniso = Math.Max(shAniso, s.ChainSvMax / s.ChainSvMin - 1);
                shSvMax = Math.Max(shSvMax, s.ChainSvMax);
                shSvMin = Math.Min(shSvMin, s.ChainSvMin);
                rMinSeen = Math.Min(rMinSeen, s.RadiusFull);
                rMaxSeen = Math.Max(rMaxSeen, s.RadiusFull);
            }

            void HurtRows(string key, Mtx[] w)
            {
                for (int h = 0; h < fm.Hurtboxes.Count; h++)
                {
                    var hb = fm.Hurtboxes[h];
                    if (hb.Joint < 0) { hcsv.Append(key).Append($",{h},{hb.Part},-1,{hb.Type},{hb.Grab},,,,,,,\n"); continue; }
                    var m = w[hb.Joint];
                    // lb_8000B1CC (lb_00B0.c:97-132): zero offset -> translation column, else MTXMultVec
                    Vec3f a = (hb.A.X == 0 && hb.A.Y == 0 && hb.A.Z == 0) ? new Vec3f(m[0, 3], m[1, 3], m[2, 3]) : F32.MultVec(m, hb.A);
                    Vec3f b = (hb.B.X == 0 && hb.B.Y == 0 && hb.B.Z == 0) ? new Vec3f(m[0, 3], m[1, 3], m[2, 3]) : F32.MultVec(m, hb.B);
                    var sv = F32.SingularValues(m);
                    double sc = Math.Cbrt(Math.Abs(F32.Det3(m)));
                    maxAniso = Math.Max(maxAniso, sv.Max / sv.Min - 1);
                    hcsv.Append(key).Append(',').Append(h).Append(',').Append(hb.Part).Append(',').Append(hb.Joint).Append(',')
                        .Append(hb.Type).Append(',').Append(hb.Grab).Append(',')
                        .Append(F(a.X)).Append(',').Append(F(a.Y)).Append(',').Append(F(a.Z)).Append(',')
                        .Append(F(b.X)).Append(',').Append(F(b.Y)).Append(',').Append(F(b.Z)).Append(',')
                        .Append(F(hb.R * sc)).Append('\n');
                }
            }

            // (a) grid
            // `angle` is the settled eased angle g = x8 - 10 in [0, 360]. A stick angle of exactly 0 deg has two
            // fixed points (MECHANICS 1.2): g = 0 (frame 10: fresh shield or approached from above) and g = 360
            // (frame 370: approached from below; absorbing). Both are emitted for m > 0 when the character tilts.
            foreach (var g in grid)
            {
                var (deg, mag) = Settled(g.Lx, g.Ly, 1);
                foreach (float gAng in (deg == 0f && mag > 0f && fm.HasTilt) ? new[] { 0f, 360f } : new[] { deg })
                {
                    float frame = 10f + gAng;
                    var s = Eval(fm, c, frame, mag, 1);
                    Track(s);
                    string key = $"grid,{g.Kx},{g.Ky},{F(gAng)},{F(mag)}";
                    csv.Append(key).Append(',').Append(F(s.Bubble.X)).Append(',').Append(F(s.Bubble.Y)).Append(',').Append(F(s.Bubble.Z))
                       .Append(',').Append(F(s.RadiusFull)).Append(',').Append(F(s.RadiusMin)).Append('\n');
                    if (hurt) HurtRows(key, s.W);
                    if (gAng == 360f) res.Grid370Rows++;
                }
            }
            res.GridCount = grid.Count;

            // (b) polar (angle 360 = frame 370, the from-below fixed point of 0 deg)
            for (int th = 0; th <= 360; th++)
                for (int k = 0; k <= 20; k++)
                {
                    float m = (float)(k / 20.0);
                    var s = Eval(fm, c, 10f + th, m, 1);
                    Track(s);
                    string key = $"polar,,,{th},{F(m)}";
                    csv.Append(key).Append(',').Append(F(s.Bubble.X)).Append(',').Append(F(s.Bubble.Y)).Append(',').Append(F(s.Bubble.Z))
                       .Append(',').Append(F(s.RadiusFull)).Append(',').Append(F(s.RadiusMin)).Append('\n');
                    if (hurt) HurtRows(key, s.W);
                    res.PolarCount++;
                }

            File.WriteAllText(Path.Combine(dataDir, $"{fm.Code}.csv"), csv.ToString());
            if (hurt) File.WriteAllText(Path.Combine(dataDir, $"{fm.Code}_hurtboxes.csv"), hcsv.ToString());

            var checks = Checks(fm, c, grid);
            res.ChecksPass = checks.All(kv => kv.Value is Dictionary<string, object?> d && d.TryGetValue("pass", out var p) && p is true);
            var ell = new Dictionary<string, object?>
            {
                ["radius_full_range_over_samples"] = new[] { rMinSeen, rMaxSeen },
                ["parent_world_scale_singular_value_range"] = new[] { shSvMin, shSvMax },
                ["max_anisotropy"] = shAniso,
                ["note"] = "The bubble is the unit sphere through the shield bone's world matrix, i.e. an ellipsoid when the " +
                           "parent chain carries non-uniform scale (Guard figatree SCA tracks). shield_radius_* use the " +
                           "geometric mean cbrt(|det|); semi-axes = b * singular values of the parent world matrix.",
            };
            WriteMeta(fm, c, dataDir, res, checks, hurt, maxAniso, ell);
            return res;
        }

        // ------------------------------------------------------------------ checks

        public static Dictionary<string, object?> Checks(FighterModel fm, CommonData c, List<(int Kx, int Ky, float Lx, float Ly)> grid)
        {
            var o = new Dictionary<string, object?>();
            float bFull = fm.BubbleScale(c, c.StartShieldHealth, 1.0f);

            // 1. m = 0 reproduces the plain ShieldPose (independent evaluation straight from the SP Joint tree,
            //    with the ItemHold scale rule of ftAnim_8006FA58) for every frame.
            {
                var sp = new Srt[fm.Joints.Count];
                float invMs = 1.0f / fm.ModelScale;
                for (int j = 0; j < sp.Length; j++)
                {
                    sp[j] = j == 0 ? default : fm.Joints[j].Sp;
                    if (j > 0 && fm.Joints[j].Part == fm.ItemHoldPart) sp[j].S = new Vec3f(invMs, invMs, invMs);
                    if (j > 0 && fm.DynamicParts.Contains(fm.Joints[j].Part)) { sp[j].R = fm.Joints[j].Rest.R; }
                }
                var wsp = fm.World(sp, 1, bFull);
                double maxJoint = 0, maxAcross = 0;
                Vec3f? first = null;
                for (int th = 0; th < 360; th += 7)
                {
                    var w = fm.World(fm.LivePose(10f + th, 0f), 1, bFull);
                    for (int j = 0; j < w.Length; j++)
                        maxJoint = Math.Max(maxJoint, Dist(new Vec3f(w[j][0, 3], w[j][1, 3], w[j][2, 3]), new Vec3f(wsp[j][0, 3], wsp[j][1, 3], wsp[j][2, 3])));
                    var b = new Vec3f(w[fm.ShieldJoint][0, 3], w[fm.ShieldJoint][1, 3], w[fm.ShieldJoint][2, 3]);
                    first ??= b;
                    maxAcross = Math.Max(maxAcross, Dist(b, first.Value));
                }
                // continuity m -> 0+
                double maxCont = 0;
                if (fm.HasTilt)
                    for (int th = 0; th < 360; th++)
                    {
                        var a0 = Eval(fm, c, 10f + th, 0f, 1).Bubble;
                        var a1 = Eval(fm, c, 10f + th, 1e-6f, 1).Bubble;
                        maxCont = Math.Max(maxCont, Dist(a0, a1));
                    }
                o["m0_equals_shieldpose"] = new Dictionary<string, object?>
                {
                    ["max_joint_world_pos_diff"] = maxJoint,
                    ["max_bubble_diff_across_angles"] = maxAcross,
                    ["max_bubble_jump_m0_vs_m1e-6"] = maxCont,
                    ["pass"] = maxJoint == 0 && maxAcross == 0 && maxCont < 1e-3,
                };
            }

            // 2. theta and theta+360 agree (API wrap), plus the animation's own 0/360 seam: A(10) vs A(370).
            {
                double maxWrap = 0;
                for (int th = 0; th < 360; th++)
                    foreach (var m in new[] { 0.25f, 0.5f, 1f })
                    {
                        var a = Eval(fm, c, FrameForAngle(th), m, 1).Bubble;
                        var b = Eval(fm, c, FrameForAngle(th + 360), m, 1).Bubble;
                        var d = Eval(fm, c, FrameForAngle(th - 360), m, 1).Bubble;
                        maxWrap = Math.Max(maxWrap, Math.Max(Dist(a, b), Dist(a, d)));
                    }
                double seam = 0, seamJ = 0;
                if (fm.HasTilt)
                {
                    seam = Dist(Eval(fm, c, 10f, 1f, 1).Bubble, Eval(fm, c, 370f, 1f, 1).Bubble);
                    var w10 = Eval(fm, c, 10f, 1f, 1).W;
                    var w370 = Eval(fm, c, 370f, 1f, 1).W;
                    for (int j = 0; j < w10.Length; j++)
                        seamJ = Math.Max(seamJ, Dist(new Vec3f(w10[j][0, 3], w10[j][1, 3], w10[j][2, 3]), new Vec3f(w370[j][0, 3], w370[j][1, 3], w370[j][2, 3])));
                }
                o["theta_wraps_360"] = new Dictionary<string, object?>
                {
                    ["max_bubble_diff"] = maxWrap,
                    ["anim_frame10_vs_frame370_bubble_diff"] = seam,
                    ["anim_frame10_vs_frame370_max_joint_diff"] = seamJ,
                    ["pass"] = maxWrap == 0,
                };
            }

            // 3. m -> 1 continuity with the skipped-blend path at m == 1.
            {
                double maxJump = 0, maxJumpNoB4 = 0;
                int worst = -1;
                if (fm.HasTilt)
                    for (int th = 0; th < 360; th++)
                    {
                        var a = Eval(fm, c, 10f + th, 1f, 1).Bubble;
                        var b = Eval(fm, c, 10f + th, 1f - 1e-6f, 1).Bubble;
                        double d = Dist(a, b);
                        if (d > maxJump) { maxJump = d; worst = th; }
                    }
                // Diagnose the b4 (TransN / part 0x35) contribution: costume/anim vs SP local SRT
                var b4 = new List<object>();
                if (fm.HasTilt)
                {
                    var a0 = fm.AnimPose(10f);
                    foreach (var p in fm.B4Parts.OrderBy(x => x))
                    {
                        int j = fm.PartToJoint(p);
                        if (j < 0) continue;
                        var an = a0[j]; var sp = fm.Joints[j].Sp;
                        double dT = Dist(an.T, sp.T), dR = Dist(an.R, sp.R), dS = Dist(an.S, sp.S);
                        bool animated = fm.Joints[j].Tracks.Count > 0;
                        bool onChain = fm.ShieldChain.Contains(j);
                        b4.Add(new Dictionary<string, object?>
                        {
                            ["part"] = p, ["joint"] = j, ["animated_by_guard"] = animated,
                            ["tracks"] = fm.Joints[j].Tracks.Select(t => (int)t.Type).ToArray(),
                            ["on_shield_chain"] = onChain,
                            ["anim_or_rest_minus_sp_at_frame10"] = new { dT, dR, dS },
                        });
                    }
                }
                o["m1_continuity"] = new Dictionary<string, object?>
                {
                    ["max_bubble_jump_m1_vs_1minus1e-6"] = maxJump,
                    ["worst_theta"] = worst,
                    ["b4_joints"] = b4,
                    // A jump here is the engine's real discontinuity (MECHANICS 3.2e), not a solver bug;
                    // the check passes if the jump is explained by b4 joints on the shield chain.
                    ["pass"] = maxJump < 1e-3 || fm.B4Parts.Any(p => fm.ShieldChain.Contains(fm.PartToJoint(p))),
                };
            }

            // 5. Easing history (ftCo_80091BC4 simulated in f32): a stick at exactly 0 deg settles at x8 = 10 from a
            //    fresh shield but at x8 = 370 when approached from below (e.g. from 270 deg); 370 is absorbing.
            {
                float fromFresh = SimulateX8(10f, 0.3f, 0f, 1, 300);
                float fromBelow = SimulateX8(280f, 0.3f, 0f, 1, 300);
                float neutralFromBelow = SimulateX8(325f, 0f, 0f, 1, 300);
                float fromAbove = SimulateX8(100f, 0.3f, 0f, 1, 300);
                float leftFromBelow = SimulateX8(280f, -0.3f, 0f, -1, 300);
                o["zero_angle_two_fixed_points"] = new Dictionary<string, object?>
                {
                    ["x8_fresh_then_(0.3,0)"] = fromFresh,
                    ["x8_from_270deg_then_(0.3,0)"] = fromBelow,
                    ["x8_from_315deg_then_neutral"] = neutralFromBelow,
                    ["x8_from_90deg_then_(0.3,0)"] = fromAbove,
                    ["x8_facing_left_from_270deg_then_(-0.3,0)"] = leftFromBelow,
                    ["pass"] = fromFresh == 10f && fromBelow == 370f && neutralFromBelow == 370f && fromAbove == 10f && leftFromBelow == 370f,
                };
            }

            // 4. facing left mirrors (x, z) for the mirrored stick.
            {
                double maxDx = 0, maxDy = 0, maxDz = 0;
                foreach (var g in grid)
                {
                    var (degR, magR) = Settled(g.Lx, g.Ly, 1);
                    var (degL, magL) = Settled(-g.Lx, g.Ly, -1);
                    if (degR != degL || magR != magL) { maxDx = double.PositiveInfinity; break; }
                    var r = Eval(fm, c, 10f + degR, magR, 1).Bubble;
                    var l = Eval(fm, c, 10f + degL, magL, -1).Bubble;
                    maxDx = Math.Max(maxDx, Math.Abs(l.X + r.X));
                    maxDy = Math.Max(maxDy, Math.Abs(l.Y - r.Y));
                    maxDz = Math.Max(maxDz, Math.Abs(l.Z + r.Z));
                }
                o["facing_left_mirror"] = new Dictionary<string, object?>
                {
                    ["max_abs(xL + xR)"] = maxDx,
                    ["max_abs(yL - yR)"] = maxDy,
                    ["max_abs(zL + zR)"] = maxDz,
                    ["note"] = "Facing is a +/-90 deg TopN Y rotation; cosf((float)pi/2) = -4.37e-8 leaves a residual of ~1e-7 * |local x|.",
                    ["pass"] = maxDy == 0 && maxDx < 1e-4 && maxDz < 1e-4,
                };
            }
            return o;
        }

        // ------------------------------------------------------------------ meta

        static void WriteMeta(FighterModel fm, CommonData c, string dataDir, RunResult res,
                              Dictionary<string, object?> checks, bool hurt, double maxAniso, Dictionary<string, object?> ell)
        {
            float bFull = fm.BubbleScale(c, c.StartShieldHealth, 1.0f);
            float bLight = fm.BubbleScale(c, c.StartShieldHealth, 0.0f);
            float bMin = fm.BubbleScale(c, 0.0f, 1.0f);
            var chainInfo = fm.ShieldChain.Select(j => new Dictionary<string, object?>
            {
                ["joint"] = j, ["part"] = fm.Joints[j].Part, ["costume_flags"] = $"0x{fm.Joints[j].Flags:X8}",
                ["classical_scale"] = (fm.Joints[j].Flags & 8) != 0,
                ["guard_tracks"] = fm.Joints[j].Tracks.Select(t => (int)t.Type).ToArray(),
                ["b4"] = fm.B4Parts.Contains(fm.Joints[j].Part),
            }).ToList();
            var hurtInfo = fm.Hurtboxes.Select((h, i) => new Dictionary<string, object?>
            {
                ["index"] = i, ["part"] = h.Part, ["joint"] = h.Joint, ["type"] = h.Type, ["grabbable"] = h.Grab,
                ["on_dynamics_bone"] = fm.DynamicParts.Contains(h.Part),
                ["descendant_of_shield_bone"] = h.Joint >= 0 && h.Joint != fm.ShieldJoint && fm.IsAncestorOrSelf(fm.ShieldJoint, h.Joint),
                ["costume_flags"] = h.Joint >= 0 ? $"0x{fm.Joints[h.Joint].Flags:X8}" : null,
            }).ToList();

            var meta = new Dictionary<string, object?>
            {
                ["code"] = fm.Code,
                ["name"] = fm.Name,
                ["ft_kind"] = fm.Kind,
                ["has_tilt"] = fm.HasTilt,
                ["tilt_note"] = fm.HasTilt ? null :
                    "Yoshi never calls ftCo_80091BC4/ftCo_80091E78 (MECHANICS 6). GuardHold (motion state 342, ftCo_SM_None) " +
                    "resets the live skeleton to the costume rest pose (ftyoshiguard.c:176); every row is the same fixed bubble. " +
                    "Bubble scale is the constant initial_shield_size (inlineB0, ftCo_Guard.c:179-180). Verify in emulator.",
                ["sources"] = new Dictionary<string, object?>
                {
                    ["fighter_data"] = $"gamedata/Pl{fm.Code}.dat",
                    ["costume_rest_pose"] = $"gamedata/Pl{fm.Code}Nr.dat",
                    ["guard_figatree"] = fm.HasTilt ? $"gamedata/{fm.FigaSource}" : null,
                    ["guard_figatree_symbol"] = fm.FigaSymbol,
                    ["common"] = "gamedata/PlCo.dat",
                },
                ["figatree_frames"] = fm.FrameCount,
                ["figatree_nodes"] = fm.FigaNodeCount,
                ["joints"] = fm.Joints.Count,
                ["parts_num"] = fm.PartsNum,
                ["optional_part_slots"] = fm.OptionalSlots,
                ["part_to_joint"] = fm.PartToJointIdx,
                ["part_to_joint_derivation"] =
                    "parts[] slots i for which ftParts_8007506C(kind, i) != 0 (PlCo.dat ftLoadCommonData pData[5] = " +
                    "Fighter_804D6540[kind], entries' byte x0) hold no costume joint; the remaining slots take the costume " +
                    "Joint tree in preorder (ftParts_8007462C, ftparts.c:457-498). Hurtbox bone_index and ModelLookupTables " +
                    "ShieldBone (x11) index parts[] (ftcoll.c:3189-3193, ftCo_Guard.c:241-244).",
                ["shield_part"] = fm.ShieldPart,
                ["shield_joint"] = fm.ShieldJoint,
                ["shield_chain_to_root"] = chainInfo,
                ["transN_on_shield_chain"] = fm.ShieldChain.Contains(fm.PartToJoint(fm.TransNPart)),
                ["item_hold_part"] = fm.ItemHoldPart,
                ["flags_b4_parts"] = fm.B4Parts.OrderBy(x => x).ToArray(),
                ["flags_b4_derivation"] = "parts[part_to_joint[FtPart_TransN]] and parts[part_to_joint[0x35]] (ftparts.c:691-692, " +
                                          "PlCo.dat BoneTables[kind]+0x04 table), plus parts[1] for Mewtwo (ftmewtwo.c:295).",
                ["dynamics_parts_b0"] = fm.DynamicParts.OrderBy(x => x).ToArray(),
                ["dynamics_descs_part_count"] = fm.DynamicDescs.Select(d => new[] { d.Part, d.Count }).ToArray(),
                ["model_scale"] = fm.ModelScale,
                ["initial_shield_size"] = fm.ShieldSize,
                ["shield_radius"] = new Dictionary<string, object?>
                {
                    ["formula"] = "b = initial_shield_size * (x264 + (1 - x264) * (health / x260) * (ls * (x2D8 - x2D4) + x2D4)) " +
                                  "[inlineB0, ftCo_Guard.c:177-191; set as the shield bone's scale, ftCo_Guard.c:241-244]. " +
                                  "The collider has size 1 in the bone's local space (ftCo_Guard.c:259-266) and the hit test measures " +
                                  "the hurt radius through the bone's world matrix (lbColl_80006E58, lbcollision.c:1407-1421), so " +
                                  "world radius = b * (uniform scale of the shield bone's parent world matrix), which includes TopN's " +
                                  "model_scaling (fighter.c:213-230).",
                    ["shield_radius_full"] = "full health (60), hard/digital press (trigger forced to 1 -> ls = 1, fighter.c:1888-1890): " +
                                             $"b = {F(bFull)} (= {F(bFull / fm.ShieldSize)} * size)",
                    ["shield_radius_min"] = $"health -> 0 limit: b = x264 * size = {F(bMin)}",
                    ["lightest_shield_full_health_b"] = F(bLight),
                    ["common_values"] = new { x260 = c.StartShieldHealth, x264 = c.MinScaleFrac, x2D4 = c.LightMin, x2D8 = c.LightMax },
                    ["chain_scale_note"] = "uniform scale = cbrt(|det|) of the parent world matrix, evaluated in double.",
                    ["ellipsoid"] = ell,
                },
                ["notes"] = fm.Notes,
                ["columns"] = new Dictionary<string, object?>
                {
                    ["sweep"] = "grid = every lstick value the engine can hold (MECHANICS 5); polar = angle 0..360 step 1 x mag 0..1 step 0.05",
                    ["stick_x/stick_y"] = "grid only: integer stick units after HSD_PadClamp (radius 80) and the 0.28 per-axis deadzone; " +
                                          "lstick = k/80. Fighter faces right, +x = forward.",
                    ["angle"] = "settled eased tilt angle g = x8 - 10 in degrees (0 = forward, 90 = up); Guard figatree frame = 10 + angle. " +
                              "Grid sticks at exactly 0 deg (y = 0, x >= 0) with mag > 0 get two rows: angle 0 (frame 10, fresh " +
                              "shield or approached from above) and angle 360 (frame 370, approached from below; absorbing). MECHANICS 1.2.",
                    ["mag"] = "settled blend weight x4 = min(1, |lstick|)",
                    ["bone_x/y/z"] = "shield bone world translation minus TopN translation (cur_pos), world axes, facing right, " +
                                     "including TopN model scale",
                    ["shield_radius_full/min"] = "see shield_radius",
                },
                ["grid_samples"] = res.GridCount,
                ["polar_samples"] = res.PolarCount,
                ["hurtboxes"] = new Dictionary<string, object?>
                {
                    ["exported"] = hurt,
                    ["file"] = hurt ? $"data/{fm.Code}_hurtboxes.csv" : null,
                    ["samples"] = "same samples as the main CSV (grid + full polar)",
                    ["endpoints"] = "lb_8000B1CC(bone, offset): offset (0,0,0) -> world translation column, else MTXMultVec(bone world mtx, offset); " +
                                    "values are world coordinates relative to TopN (cur_pos = 0), facing right.",
                    ["radius"] = "file radius * cbrt(|det(bone world matrix)|) (the hit test scales the local radius through the " +
                                 "bone's world matrix, lbcollision.c:1407-1421); includes model_scaling and joint scales.",
                    ["max_bone_matrix_anisotropy"] = maxAniso,
                    ["anisotropy_note"] = "max over samples/hurtboxes of (largest / smallest singular value - 1) of the bone world matrix; " +
                                          "where > 0 the engine's effective radius depends on direction and `radius` is the geometric mean.",
                    ["shield_bone_scale_used"] = F(bFull),
                    ["dynamics_bones"] = "hurtboxes on dynamics (flags_b0) bones use the costume rest local pose; the engine simulates them.",
                    ["guard_intangibility"] = "Posed geometry only. Shield-state hurtbox intangibility is not applied.",
                    ["list"] = hurtInfo,
                },
                ["checks"] = checks,
                ["float_model"] = "All pose math in float32 in decomp operation order. Doubles used only where the source uses them " +
                                  "(1.0/fterm, 1.0/scale, M_PI_2*facing, lb_8000D008's pi-atanf) and for diagnostics " +
                                  "(radius chain scale cbrt(det), anisotropy, check distances). See tools/ShieldPose/README.md.",
            };
            var opts = new JsonSerializerOptions { WriteIndented = true, IncludeFields = true, NumberHandling = System.Text.Json.Serialization.JsonNumberHandling.AllowNamedFloatingPointLiterals };
            File.WriteAllText(Path.Combine(dataDir, $"{fm.Code}_meta.json"), JsonSerializer.Serialize(meta, opts));
        }

        // ------------------------------------------------------------------ sanity print / pose dump

        public static void Sanity(FighterModel fm, CommonData c)
        {
            Console.WriteLine($"  sanity {fm.Code} ({fm.Name}), shield part {fm.ShieldPart} -> joint {fm.ShieldJoint}, chain [{string.Join(",", fm.ShieldChain)}]");
            foreach (var (label, kx, ky) in new[] { ("neutral", 0, 0), ("full up", 0, 80), ("full down", 0, -80), ("full forward", 80, 0), ("full back", -80, 0) })
            {
                var (deg, mag) = Settled(kx / 80f, ky / 80f, 1);
                var s = Eval(fm, c, 10f + deg, mag, 1);
                Console.WriteLine($"    {label,-13} angle {deg,6:0.###} mag {mag:0.###}  bubble ({s.Bubble.X,9:0.0000}, {s.Bubble.Y,9:0.0000}, {s.Bubble.Z,9:0.0000})  r_full {s.RadiusFull:0.000} r_min {s.RadiusMin:0.000}");
            }
        }

        public static void PoseDump(FighterModel fm, CommonData c, float angle, float mag, int facing, string path)
        {
            float frame = FrameForAngle(angle);
            float bFull = fm.BubbleScale(c, c.StartShieldHealth, 1.0f);
            var live = fm.LivePose(frame, mag);
            var w = fm.World(live, facing, bFull);
            var sb = new StringBuilder();
            sb.AppendLine($"# {fm.Code} {fm.Name} angle={F(angle)} frame={F(frame)} mag={F(mag)} facing={facing} shield_joint={fm.ShieldJoint} (part {fm.ShieldPart})");
            sb.AppendLine("joint,part,parent,depth,costume_flags,quat,rx,ry,rz,qx,qy,qz,qw,sx,sy,sz,tx,ty,tz,world_x,world_y,world_z,is_shield,b4,dynamics");
            for (int j = 0; j < w.Length; j++)
            {
                var ji = fm.Joints[j]; var s = live[j];
                sb.Append($"{j},{ji.Part},{ji.Parent},{ji.Depth},0x{ji.Flags:X8},{(s.Quat ? 1 : 0)},")
                  .Append($"{F(s.R.X)},{F(s.R.Y)},{F(s.R.Z)},{F(s.Q.X)},{F(s.Q.Y)},{F(s.Q.Z)},{F(s.Q.W)},")
                  .Append($"{F(s.S.X)},{F(s.S.Y)},{F(s.S.Z)},{F(s.T.X)},{F(s.T.Y)},{F(s.T.Z)},")
                  .Append($"{F(w[j][0, 3])},{F(w[j][1, 3])},{F(w[j][2, 3])},{(j == fm.ShieldJoint ? 1 : 0)},")
                  .Append($"{(fm.B4Parts.Contains(ji.Part) ? 1 : 0)},{(fm.DynamicParts.Contains(ji.Part) ? 1 : 0)}\n");
            }
            File.WriteAllText(path, sb.ToString());
        }
    }
}
