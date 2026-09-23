using HSDRaw;
using HSDRaw.Common;
using HSDRaw.Common.Animation;
using HSDRaw.Melee;
using HSDRaw.Melee.Pl;

namespace ShieldPose;

/// <summary>Local SRT of one joint, as stored in HSD_JObj (rotate is Euler unless Quat is set).</summary>
public struct Srt
{
    public Vec3f R;
    public Quatf Q;
    public bool Quat;
    public Vec3f S;
    public Vec3f T;
}

public sealed class JointInfo
{
    public int Index;          // preorder joint index (0 = TopN)
    public int Parent = -1;    // preorder index of the parent, -1 for the root
    public int Depth;
    public uint Flags;         // costume (Pl??Nr.dat) joint flags -> live JObj flags
    public bool HasRObj;
    public Srt Rest;           // costume rest pose
    public Srt Sp;             // ShieldPose (FighterData+0x20) pose
    public int Part = -1;      // fp->parts[] index
    public List<FigaTrackData> Tracks = new();
}

public static class CharTable
{
    // code -> (Ft_Kind enum value, display name). Ft_Kind order: ft/forward.h:92-126.
    public static readonly (string Code, int Kind, string Name)[] All =
    {
        ("Mr", 0, "Mario"), ("Fx", 1, "Fox"), ("Ca", 2, "CaptainFalcon"), ("Dk", 3, "DonkeyKong"),
        ("Kb", 4, "Kirby"), ("Kp", 5, "Bowser"), ("Lk", 6, "Link"), ("Sk", 7, "Sheik"), ("Ns", 8, "Ness"),
        ("Pe", 9, "Peach"), ("Pp", 10, "Popo"), ("Nn", 11, "Nana"), ("Pk", 12, "Pikachu"), ("Ss", 13, "Samus"),
        ("Ys", 14, "Yoshi"), ("Pr", 15, "Jigglypuff"), ("Mt", 16, "Mewtwo"), ("Lg", 17, "Luigi"),
        ("Ms", 18, "Marth"), ("Zd", 19, "Zelda"), ("Cl", 20, "YoungLink"), ("Dr", 21, "DrMario"),
        ("Fc", 22, "Falco"), ("Pc", 23, "Pichu"), ("Gw", 24, "MrGameAndWatch"), ("Gn", 25, "Ganondorf"),
        ("Fe", 26, "Roy"),
    };
}

public sealed class CommonData
{
    public float StickDeadzoneX, StickDeadzoneY, TiltK;
    public float StartShieldHealth, MinScaleFrac, LightMin, LightMax;
    public int[] PartsNum = Array.Empty<int>();
    public byte[][] PartToJoint = Array.Empty<byte[]>();   // FighterPartsTable.part_to_joint (FtPart enum -> parts index)
    public int[][] OptionalParts = Array.Empty<int[]>();   // Fighter_804D6540[kind] entries' x0

    public static CommonData Load(string path)
    {
        var file = new HSDRawFile(path);
        var root = file.Roots.First(r => r.Data is SBM_ftLoadCommonData);
        var c = (SBM_ftLoadCommonData)root.Data;
        var s = c.CommonAttributes._s;
        var cd = new CommonData
        {
            StickDeadzoneX = s.GetFloat(0x000),
            StickDeadzoneY = s.GetFloat(0x004),
            StartShieldHealth = s.GetFloat(0x260),
            MinScaleFrac = s.GetFloat(0x264),
            LightMin = s.GetFloat(0x2D4),
            LightMax = s.GetFloat(0x2D8),
            TiltK = s.GetFloat(0x44C),
        };
        var bt = c.BoneTables;
        int n = bt.Length;
        cd.PartsNum = new int[n];
        cd.PartToJoint = new byte[n][];
        for (int i = 0; i < n; i++)
        {
            var t = bt[i];
            cd.PartsNum[i] = t.BoneCount;
            var p2j = t._s.GetReference<HSDAccessor>(0x04);
            cd.PartToJoint[i] = p2j?._s.GetData() ?? Array.Empty<byte>();
        }
        // pData[5] = Fighter_804D6540: per kind {Fighter_804D6540_x0_t* x0; int x4}
        var ft = c._s.GetReference<HSDAccessor>(0x14);
        cd.OptionalParts = new int[n][];
        for (int i = 0; i < n; i++)
        {
            var e = ft?._s.GetReference<HSDAccessor>(i * 4);
            if (e == null) { cd.OptionalParts[i] = Array.Empty<int>(); continue; }
            int cnt = e._s.GetInt32(0x04);
            var arr = e._s.GetReference<HSDAccessor>(0x00);
            var list = new List<int>();
            for (int k = 0; k < cnt && arr != null; k++) list.Add(arr._s.GetByte(k * 4));
            cd.OptionalParts[i] = list.ToArray();
        }
        return cd;
    }
}

public sealed class FighterModel
{
    public string Code = "", Name = "";
    public int Kind;
    public List<JointInfo> Joints = new();
    public int PartsNum;
    public int[] PartToJointIdx = Array.Empty<int>();   // parts index -> joint index (-1 for optional slot)
    public int[] OptionalSlots = Array.Empty<int>();
    public int ShieldPart, ShieldJoint, ItemHoldPart;
    public HashSet<int> B4Parts = new();
    public HashSet<int> DynamicParts = new();
    public List<(int Part, int Count)> DynamicDescs = new();   // flags_b0 candidates (FighterData+0x2C dynamics)
    public float ModelScale, ShieldSize;
    public float FrameCount;
    public int FigaNodeCount;
    public string FigaSource = "";
    public string FigaSymbol = "";
    public bool HasTilt = true;
    public List<string> Notes = new();
    public List<(int Part, int Joint, int Type, int Grab, Vec3f A, Vec3f B, float R)> Hurtboxes = new();
    public int TransNPart = 1;
    public List<int> ShieldChain = new();   // joint indices from the shield bone up to the root

    const uint JOBJ_CLASSICAL_SCALE = 1 << 3;
    const uint JOBJ_INSTANCE = 1 << 12;
    const uint JOBJ_USE_QUATERNION = 1 << 17;
    const uint JOBJ_JOINT_MASK = 3u << 21;
    const uint JOBJ_USER_DEF_MTX = 1 << 23;
    const uint JOBJ_MTX_INDEP_PARENT = 1 << 24;
    const uint JOBJ_MTX_INDEP_SRT = 1 << 25;

    static List<(HSD_JOBJ J, int Parent, int Depth)> Preorder(HSD_JOBJ root)
    {
        // Same order as ftAnim_GetNextJointInTree (ftanim.c:94-127) / ftParts_8007462C.
        var list = new List<(HSD_JOBJ, int, int)>();
        void Rec(HSD_JOBJ j, int parent, int depth)
        {
            for (var cur = j; cur != null; cur = cur.Next)
            {
                int idx = list.Count;
                list.Add((cur, parent, depth));
                if (cur.Child != null) Rec(cur.Child, idx, depth + 1);
            }
        }
        Rec(root, -1, 0);
        return list;
    }

    static Srt SrtOf(HSD_JOBJ j) => new Srt
    {
        R = new Vec3f(j.RX, j.RY, j.RZ),
        S = new Vec3f(j.SX, j.SY, j.SZ),
        T = new Vec3f(j.TX, j.TY, j.TZ),
    };

    static HSD_FigaTree? LoadFiga(string ajPath, SBM_FighterData fd, int index, out string symbol, out int size)
    {
        symbol = "";
        var cmds = fd.FighterActionTable.Commands;
        var e = cmds[index];
        size = e.AnimationSize;
        if (e.AnimationSize <= 0) return null;
        var aj = File.ReadAllBytes(ajPath);
        var slice = new byte[e.AnimationSize];
        Array.Copy(aj, e.AnimationOffset, slice, 0, e.AnimationSize);
        var f = new HSDRawFile(slice);
        var r = f.Roots.FirstOrDefault(x => x.Data is HSD_FigaTree);
        if (r == null) return null;
        symbol = r.Name;
        return (HSD_FigaTree)r.Data;
    }

    public static FighterModel Load(string gamedata, string code, CommonData common)
    {
        var (c, kind, name) = CharTable.All.First(x => x.Code == code);
        var fm = new FighterModel { Code = c, Kind = kind, Name = name };

        var datFile = new HSDRawFile(Path.Combine(gamedata, $"Pl{code}.dat"));
        var fd = (SBM_FighterData)datFile.Roots.First(r => r.Data is SBM_FighterData).Data;
        fm.ModelScale = fd.Attributes.ModelScale;
        fm.ShieldSize = fd.Attributes.ShieldSize;
        fm.ShieldPart = fd.ModelLookupTables.ShieldBone;
        fm.ItemHoldPart = fd.ModelLookupTables.ItemHoldBone;

        // ---------- costume rest skeleton
        var nrFile = new HSDRawFile(Path.Combine(gamedata, $"Pl{code}Nr.dat"));
        var nrRoot = nrFile.Roots.FirstOrDefault(r => r.Name.EndsWith("_joint") && !r.Name.Contains("matanim"))
                     ?? throw new Exception($"Pl{code}Nr.dat: no *_joint root (roots: {string.Join(",", nrFile.Roots.Select(r => r.Name))})");
        var costume = new HSD_JOBJ { _s = nrRoot.Data._s };
        var cl = Preorder(costume);

        // ---------- ShieldPose skeleton
        var spRoot = fd.ShieldPoseContainer?.ShieldPose;
        if (spRoot == null)
        {
            if (kind != 14) throw new Exception("no ShieldPose (FighterData+0x20)");
            fm.Notes.Add("no ShieldPose in FighterData+0x20 (Yoshi does not use it); SP columns = costume rest");
        }
        var sl = spRoot != null ? Preorder(spRoot) : cl;
        if (sl.Count != cl.Count)
            fm.Notes.Add($"ShieldPose joint count {sl.Count} != costume joint count {cl.Count}");
        for (int i = 0; i < Math.Min(sl.Count, cl.Count); i++)
            if (sl[i].Parent != cl[i].Parent)
            {
                fm.Notes.Add($"ShieldPose/costume topology differs at joint {i}");
                break;
            }

        for (int i = 0; i < cl.Count; i++)
        {
            var (j, parent, depth) = cl[i];
            var ji = new JointInfo
            {
                Index = i, Parent = parent, Depth = depth, Flags = (uint)j.Flags, HasRObj = j.ROBJ != null,
                Rest = SrtOf(j),
                Sp = i < sl.Count ? SrtOf(sl[i].J) : SrtOf(j),
            };
            fm.Joints.Add(ji);
        }

        // ---------- part <-> joint mapping (ftParts_8007506C optional slots, ftparts.c:712-727)
        fm.PartsNum = common.PartsNum[kind];
        fm.OptionalSlots = common.OptionalParts[kind];
        fm.PartToJointIdx = new int[fm.PartsNum];
        {
            int j = 0;
            for (int p = 0; p < fm.PartsNum; p++)
            {
                if (fm.OptionalSlots.Contains(p)) { fm.PartToJointIdx[p] = -1; continue; }
                fm.PartToJointIdx[p] = j;
                if (j < fm.Joints.Count) fm.Joints[j].Part = p;
                j++;
            }
            if (j != fm.Joints.Count)
                fm.Notes.Add($"parts_num {fm.PartsNum} - optional {fm.OptionalSlots.Length} = {j} != costume joints {fm.Joints.Count}");
        }
        fm.ShieldJoint = fm.PartToJoint(fm.ShieldPart);

        // flags_b4: parts[part_to_joint[TransN]] and parts[part_to_joint[0x35]] (ftparts.c:691-692);
        // Mewtwo additionally parts[1] (ftmewtwo.c:295).
        var p2j = common.PartToJoint[kind];
        fm.TransNPart = p2j.Length > 1 ? p2j[1] : 1;
        fm.B4Parts.Add(fm.TransNPart);
        if (p2j.Length > 0x35 && p2j[0x35] != 0xFF && p2j[0x35] < fm.PartsNum) fm.B4Parts.Add(p2j[0x35]);
        else fm.Notes.Add($"part_to_joint[0x35] = {(p2j.Length > 0x35 ? p2j[0x35] : -1)} (no valid part; flags_b4 write lands outside parts[])");
        if (kind == 16) fm.B4Parts.Add(1);

        // dynamics bones (flags_b0), FighterData+0x2C. Each DynamicDesc names a start part and a chain
        // of `count` joints following child links (ftdynamics.c:37-80). Informational: the walkers skip them.
        try
        {
            var phys = fd.Physics;
            if (phys != null && phys.DynamicDescCount > 0)
            {
                foreach (var d in phys.DynamicDesc.Array.Take(phys.DynamicDescCount))
                {
                    int part = d.BoneIndex;
                    int count = d._s.GetInt32(0x08);
                    fm.DynamicDescs.Add((part, count));
                    if (Environment.GetEnvironmentVariable("SP_DEBUG") == "1") Console.Error.WriteLine($"[{code}] dynamicsNum={phys.DynamicDescCount} desc part={part} count={count}");
                    // ftdynamics.c:62-80 walks `count` descs, bone_id++ per step
                    for (int k = 0; k < Math.Max(1, count); k++)
                        if (part + k < fm.PartsNum) fm.DynamicParts.Add(part + k);
                }
            }
        }
        catch (Exception e) { fm.Notes.Add("dynamics parse failed: " + e.Message); }

        // ---------- Guard figatree (subaction 38)
        HSD_FigaTree? tree = null;
        string ajCode = code;
        {
            var t = LoadFiga(Path.Combine(gamedata, $"Pl{code}AJ.dat"), fd, 38, out var sym, out var size);
            if (t == null && code == "Nn")
            {
                // ftData_80085FD4 (ftdata.c:1840-1849): Nana falls back to Popo's entry when hers is empty.
                var ppFile = new HSDRawFile(Path.Combine(gamedata, "PlPp.dat"));
                var ppFd = (SBM_FighterData)ppFile.Roots.First(r => r.Data is SBM_FighterData).Data;
                t = LoadFiga(Path.Combine(gamedata, "PlPpAJ.dat"), ppFd, 38, out sym, out size);
                ajCode = "Pp";
            }
            tree = t;
            fm.FigaSymbol = sym;
        }
        if (tree == null)
        {
            fm.HasTilt = false;
            fm.FigaSource = "none";
        }
        else
        {
            fm.FigaSource = $"Pl{ajCode}AJ.dat action 38";
            fm.FrameCount = tree.FrameCount;
            if ((tree.Type & 1) == 0) fm.Notes.Add($"figatree type {tree.Type}: CLASSICAL_SCALE would be cleared on J2 (irrelevant to live pose)");
            var nodes = tree.Nodes;
            fm.FigaNodeCount = nodes.Count;
            // ftAnim_8006F4C8: node k -> k-th part with flags_b1 that is not an unselected optional part.
            // Optional parts are absent (no hat) or attached-but-unselected (x594_bits = 0), so
            // node k -> joint k of the costume skeleton.
            if (nodes.Count != fm.Joints.Count)
                fm.Notes.Add($"figatree nodes {nodes.Count} != costume joints {fm.Joints.Count}");
            for (int k = 0; k < Math.Min(nodes.Count, fm.Joints.Count); k++)
            {
                foreach (var tr in nodes[k].Tracks)
                {
                    var s = tr._s;
                    var buf = s.GetReference<HSDAccessor>(0x08)?._s.GetData() ?? Array.Empty<byte>();
                    fm.Joints[k].Tracks.Add(new FigaTrackData
                    {
                        Length = s.GetUInt16(0x00),
                        StartFrame = (short)s.GetUInt16(0x02),
                        Type = s.GetByte(0x04),
                        FracValue = s.GetByte(0x05),
                        FracSlope = s.GetByte(0x06),
                        Data = buf,
                    });
                }
            }
        }

        // ---------- hurtboxes (bone index = parts index, ftcoll.c:3189-3193)
        foreach (var h in fd.Hurtboxes?.Hurtboxes ?? Array.Empty<SBM_Hurtbox>())
            fm.Hurtboxes.Add((h.BoneIndex, fm.PartToJoint(h.BoneIndex), (int)h.Type, h.Grabbable,
                new Vec3f(h.X1, h.Y1, h.Z1), new Vec3f(h.X2, h.Y2, h.Z2), h.Size));

        for (int j = fm.ShieldJoint; j >= 0; j = fm.Joints[j].Parent) fm.ShieldChain.Add(j);

        fm.Validate();
        return fm;
    }

    public int PartToJoint(int part) => part >= 0 && part < PartToJointIdx.Length ? PartToJointIdx[part] : -1;

    void Validate()
    {
        foreach (var j in Joints)
        {
            var bad = new List<string>();
            if ((j.Flags & JOBJ_INSTANCE) != 0) bad.Add("INSTANCE");
            if ((j.Flags & JOBJ_JOINT_MASK) != 0) bad.Add("IK");
            if ((j.Flags & JOBJ_USER_DEF_MTX) != 0) bad.Add("USER_DEF_MTX");
            if ((j.Flags & JOBJ_MTX_INDEP_PARENT) != 0) bad.Add("MTX_INDEP_PARENT");
            if ((j.Flags & JOBJ_MTX_INDEP_SRT) != 0) bad.Add("MTX_INDEP_SRT");
            if ((j.Flags & JOBJ_USE_QUATERNION) != 0) bad.Add("USE_QUATERNION(costume)");
            if (j.HasRObj) bad.Add("ROBJ");
            if (bad.Count > 0 && RelevantJoints().Contains(j.Index))
                Notes.Add($"joint {j.Index} (part {j.Part}) on a shield/hurtbox chain has {string.Join("|", bad)} (not modelled)");
        }
        foreach (var t in Joints.SelectMany(j => j.Tracks).Select(t => t.Type).Distinct())
            if (!(t >= 1 && t <= 3) && !(t >= 5 && t <= 10))
                Notes.Add(t is 11 or 12 ? $"figatree has track type {t} (HSD_A_J_NODE/BRANCH: visibility only, jobj.c:420-433; no SRT effect)" : $"figatree has track type {t} (not modelled)");
        foreach (var p in DynamicParts)
        {
            int j = PartToJoint(p);
            if (ShieldChain.Contains(j)) Notes.Add($"dynamics part {p} is on the shield chain");
        }
    }

    HashSet<int>? _relevant;
    public HashSet<int> RelevantJoints()
    {
        if (_relevant != null) return _relevant;
        var set = new HashSet<int>();
        void Up(int j) { for (; j >= 0; j = Joints[j].Parent) set.Add(j); }
        Up(ShieldJoint);
        foreach (var h in Hurtboxes) if (h.Joint >= 0) Up(h.Joint);
        return _relevant = set;
    }

    public bool IsAncestorOrSelf(int anc, int j)
    {
        for (; j >= 0; j = Joints[j].Parent) if (j == anc) return true;
        return false;
    }

    // ================================================================== pose evaluation

    readonly Dictionary<uint, Srt[]> _animCache = new();

    /// <summary>Steps (c)+(d) of ftCo_80091E78 for frame f: costume rest (ftAnim_8006FB88) then Guard tracks.</summary>
    public Srt[] AnimPose(float frame)
    {
        uint key = BitConverter.SingleToUInt32Bits(frame);
        if (_animCache.TryGetValue(key, out var cached)) return cached;
        var a = new Srt[Joints.Count];
        float invMs = 1.0f / ModelScale;
        for (int j = 0; j < Joints.Count; j++)
        {
            var ji = Joints[j];
            var s = ji.Rest;           // lb_8000B4FC: full SRT from the costume Joint, quaternion flag cleared
            if (j >= 1 && ji.Part == ItemHoldPart)
                s.S = new Vec3f(invMs, invMs, invMs); // ftCommon_8007F6A4 (ftcommon.c:1434-1441)
            s.Quat = false;
            if (j == 0 || !DynamicParts.Contains(ji.Part))
            {
                foreach (var tr in ji.Tracks)
                {
                    var v = FObjInterp.Evaluate(tr, frame, FrameCount);
                    if (v is not float val) continue;
                    switch (tr.Type)
                    {
                        case 1: s.R.X = val; break;
                        case 2: s.R.Y = val; break;
                        case 3: s.R.Z = val; break;
                        case 5: s.T.X = val; break;
                        case 6: s.T.Y = val; break;
                        case 7: s.T.Z = val; break;
                        case 8: s.S.X = MathF.Abs(val) < 1e-3f ? 1e-3f : val; break;
                        case 9: s.S.Y = MathF.Abs(val) < 1e-3f ? 1e-3f : val; break;
                        case 10: s.S.Z = MathF.Abs(val) < 1e-3f ? 1e-3f : val; break;
                    }
                }
            }
            a[j] = s;
        }
        _animCache[key] = a;
        return a;
    }

    /// <summary>lb_8000C868(SP, J2, J2, t = 1-w, t_inv = w), lb/lb_00B0.c:560-641.</summary>
    static Srt BlendJointToward(Srt sp, Srt j2, float t, float tinv)
    {
        var o = j2;
        o.T.X = (sp.T.X * t) + (j2.T.X * tinv);
        o.T.Y = (sp.T.Y * t) + (j2.T.Y * tinv);
        o.T.Z = (sp.T.Z * t) + (j2.T.Z * tinv);
        o.S.X = (sp.S.X * t) + (j2.S.X * tinv);
        o.S.Y = (sp.S.Y * t) + (j2.S.Y * tinv);
        o.S.Z = (sp.S.Z * t) + (j2.S.Z * tinv);
        if (!j2.Quat)
        {
            float dx = sp.R.X - j2.R.X, dy = sp.R.Y - j2.R.Y, dz = sp.R.Z - j2.R.Z;
            if (MathF.Abs(dx) <= 1e-4f && MathF.Abs(dy) <= 1e-4f && MathF.Abs(dz) <= 1e-4f)
            {
                o.R = sp.R;
                o.Quat = false;
                return o;
            }
        }
        var qa = F32.EulerToQuat(sp.R.X, sp.R.Y, sp.R.Z);
        var qb = j2.Quat ? j2.Q : F32.EulerToQuat(j2.R.X, j2.R.Y, j2.R.Z);
        float sx = (qa.X + qb.X) * (qa.X + qb.X), sy = (qa.Y + qb.Y) * (qa.Y + qb.Y);
        float sz = (qa.Z + qb.Z) * (qa.Z + qb.Z), sw = (qa.W + qb.W) * (qa.W + qb.W);
        float ddx = (qa.X - qb.X) * (qa.X - qb.X), ddy = (qa.Y - qb.Y) * (qa.Y - qb.Y);
        float ddz = (qa.Z - qb.Z) * (qa.Z - qb.Z), ddw = (qa.W - qb.W) * (qa.W - qb.W);
        if (ddx + ddy + ddz + ddw > sx + sy + sz + sw)
            qb = new Quatf(-qb.X, -qb.Y, -qb.Z, -qb.W);
        o.Q = F32.Slerp(qa, qb, tinv);
        o.Quat = true;
        return o;
    }

    /// <summary>
    /// Live local pose in Guard (arg1 = 1) for settled tilt frame f = x8 and weight m = x4.
    /// Mirrors ftCo_80091E78 (ftCo_Guard.c:214-248). Joint 0 (TopN) is filled by <see cref="World"/>.
    /// </summary>
    public Srt[] LivePose(float frame, float m)
    {
        var live = new Srt[Joints.Count];
        for (int j = 0; j < Joints.Count; j++) live[j] = Joints[j].Rest; // b0/b5/untouched parts keep rest (see README)
        if (!HasTilt)
        {
            // Yoshi: GuardHold resets the live skeleton to the costume rest pose (ftyoshiguard.c:176),
            // motion state 342 has no subaction (ftCo_SM_None).
            ApplyRestWithItemHold(live, useSp: false);
            return live;
        }
        if (m == 0.0f)
        {
            // x4 == 0, arg1 >= 1: ftAnim_8006FA58(fp, TransN, SP->child) (ftanim.c:802-828)
            ApplyRestWithItemHold(live, useSp: true);
            return live;
        }
        var a = AnimPose(frame);
        for (int j = 1; j < Joints.Count; j++)
        {
            int part = Joints[j].Part;
            if (DynamicParts.Contains(part)) continue;          // !b0 (b5 assumed clear in Guard)
            var l = a[j];
            if (m < 1.0f)                                        // (e) ftAnim_80070108, skipped when x4 == 1
            {
                if (B4Parts.Contains(part)) { l = Joints[j].Sp; l.Quat = false; }
                else l = BlendJointToward(Joints[j].Sp, a[j], 1 - m, m);
            }
            live[j] = l;                                         // (f) ftAnim_8006FF74: copy J2 -> live
        }
        return live;
    }

    void ApplyRestWithItemHold(Srt[] live, bool useSp)
    {
        float invMs = 1.0f / ModelScale;
        for (int j = 1; j < Joints.Count; j++)
        {
            int part = Joints[j].Part;
            var src = useSp ? Joints[j].Sp : Joints[j].Rest;
            if (part == ItemHoldPart)
            {
                if (DynamicParts.Contains(part)) { live[j].T = src.T; }
                else { live[j].R = src.R; live[j].T = src.T; live[j].Quat = false; }
                live[j].S = new Vec3f(invMs, invMs, invMs);
            }
            else if (DynamicParts.Contains(part)) { live[j].S = src.S; live[j].T = src.T; }
            else { live[j] = src; live[j].Quat = false; }
        }
    }

    /// <summary>
    /// World matrices (HSD_JObjMakeMatrix, jobj.c:138-195) for the live pose. TopN: T = 0,
    /// R = (0, facing*pi/2, 0), S = model scale (fighter.c:213-230, 1175-1177). The shield bone's
    /// scale is overwritten with <paramref name="bubbleScale"/> (ftCo_Guard.c:241-244).
    /// </summary>
    public Mtx[] World(Srt[] live, int facing, float bubbleScale)
    {
        var top = new Srt
        {
            R = new Vec3f(0.0f, (float)(Math.PI / 2 * facing), 0.0f),
            S = new Vec3f(ModelScale, ModelScale, ModelScale),
            T = new Vec3f(0, 0, 0),
        };
        live[0] = top;
        if (ShieldJoint >= 0) live[ShieldJoint].S = new Vec3f(bubbleScale, bubbleScale, bubbleScale);

        int n = Joints.Count;
        var w = new Mtx[n];
        var scl = new Vec3f?[n];
        for (int j = 0; j < n; j++)
        {
            var ji = Joints[j];
            var s = live[j];
            Vec3f? pscl = ji.Parent >= 0 ? scl[ji.Parent] : null;
            if ((ji.Flags & JOBJ_CLASSICAL_SCALE) != 0)
                scl[j] = pscl;
            else
                scl[j] = pscl is Vec3f ps ? new Vec3f(s.S.X * ps.X, s.S.Y * ps.Y, s.S.Z * ps.Z) : s.S;
            Mtx local = s.Quat ? F32.MtxSRTQuat(s.S, s.Q, s.T, pscl) : F32.MtxSRT(s.S, s.R, s.T, pscl);
            w[j] = ji.Parent >= 0 ? F32.Concat(w[ji.Parent], local) : local;
        }
        return w;
    }

    // ================================================================== shield scale

    /// <summary>inlineB0 (ftCo_Guard.c:177-191) in f32. Yoshi: constant initial_shield_size.</summary>
    public float BubbleScale(CommonData c, float health, float lightshield)
    {
        if (Kind == 14) return ShieldSize;
        float n1 = (health / c.StartShieldHealth) * (lightshield * (c.LightMax - c.LightMin) + c.LightMin);
        float n2 = 1 - c.MinScaleFrac;
        float n3 = n2 * n1 + c.MinScaleFrac;
        return n3 * ShieldSize;
    }
}
