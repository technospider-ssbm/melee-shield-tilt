// Port of the HSD FObj interpreter (sysdolphin/baselib/fobj.c) and the parts of
// HSD_AObjReqAnim / HSD_AObjInterpretAnim (baselib/aobj.c:91-172) that the tilt
// path exercises: request frame f, interpret once with rate 0 (AOBJ_FIRST_PLAY),
// then stop the AObj if end_frame <= f (non-looping figatree, flags = 0).
namespace ShieldPose;

public sealed class FigaTrackData
{
    public ushort Length;
    public short StartFrame;   // FigaTrack.startframe (u16) -> HSD_FObj.startframe (s16)
    public byte Type;          // HSD_A_J_* track type
    public byte FracValue;
    public byte FracSlope;
    public byte[] Data = Array.Empty<byte>();
}

public static class FObjInterp
{
    const int OP_NONE = 0, OP_CON = 1, OP_LIN = 2, OP_SPL0 = 3, OP_SPL = 4, OP_SLP = 5, OP_KEY = 6;

    sealed class St
    {
        public FigaTrackData D = null!;
        public int Ad;         // offset into D.Data
        public byte Flags;
        public byte Op, OpIntrp;
        public ushort NbPack;
        public ushort Fterm;
        public float Time, P0, P1, D0, D1;
    }

    static uint GetState(St f) => (uint)(f.Flags & 0xF);
    static uint SetState(St f, uint s) { f.Flags = (byte)((s & 0xF) | (uint)(f.Flags & 0xF0)); return s; }

    static float ParseFloat(St f, byte frac)
    {
        var d = f.D.Data;
        if (frac == 0) // HSD_A_FRAC_FLOAT: little-endian IEEE single
        {
            uint u = (uint)d[f.Ad] | ((uint)d[f.Ad + 1] << 8) | ((uint)d[f.Ad + 2] << 16) | ((uint)d[f.Ad + 3] << 24);
            f.Ad += 4;
            return BitConverter.UInt32BitsToSingle(u);
        }
        int denom = 1 << (frac & 0x1F);
        float numer;
        switch (frac & 0xE0)
        {
            case 0x60: numer = (sbyte)d[f.Ad]; f.Ad += 1; break;                       // S8
            case 0x80: numer = d[f.Ad]; f.Ad += 1; break;                              // U8
            case 0x20: numer = (short)(((sbyte)d[f.Ad + 1] << 8) | d[f.Ad]); f.Ad += 2; break; // S16
            case 0x40: numer = (ushort)((d[f.Ad + 1] << 8) | d[f.Ad]); f.Ad += 2; break;       // U16
            default: return 0.0f;
        }
        return numer / denom;
    }

    static uint ParsePackInfo(St f)
    {
        var d = f.D.Data;
        byte b = d[f.Ad++];
        uint nb = (uint)(((b >> 4) & 7) + 1);
        int shift = 3;
        if ((b & 0x80) == 0) return nb;
        do
        {
            b = d[f.Ad++];
            nb += (uint)((b & 0x7F) << shift);
            shift += 7;
        } while ((b & 0x80) != 0);
        return nb;
    }

    static int ParseWait(St f)
    {
        var d = f.D.Data;
        int wait = 0, shift = 0;
        byte b;
        do
        {
            b = d[f.Ad++];
            wait |= (b & 0x7F) << shift;
            shift += 7;
        } while ((b & 0x80) != 0);
        return wait;
    }

    static void LaunchKeyData(St f)
    {
        if ((f.Flags & 0x40) != 0)
        {
            f.OpIntrp = f.Op;
            f.Flags = (byte)(f.Flags & ~0x40);
            f.Flags |= 0x80;
            f.P0 = f.P1;
        }
    }

    static uint LoadWait(St f)
    {
        if ((uint)f.Ad >= f.D.Length) return 6;
        f.Fterm = (ushort)ParseWait(f);
        f.Flags |= 0x20;
        return SetState(f, 2);
    }

    static uint LoadData(St f)
    {
        if ((uint)f.Ad >= f.D.Length) return 6;
        f.OpIntrp = f.Op;
        if (f.NbPack == 0)
        {
            f.Op = (byte)(f.D.Data[f.Ad] & 0xF);
            f.NbPack = (ushort)ParsePackInfo(f);
        }
        f.NbPack -= 1;
        uint st = GetState(f);
        uint next = st == 1 ? 3u : 4u;
        switch (f.Op)
        {
            case OP_CON:
            case OP_LIN:
                f.P0 = f.P1;
                f.P1 = ParseFloat(f, f.D.FracValue);
                if (f.OpIntrp != OP_SLP) { f.D0 = f.D1; f.D1 = 0.0f; }
                return SetState(f, next);
            case OP_SPL0:
                f.P0 = f.P1;
                f.D0 = f.D1;
                f.P1 = ParseFloat(f, f.D.FracValue);
                f.D1 = 0.0f;
                return SetState(f, next);
            case OP_SPL:
                f.P0 = f.P1;
                f.P1 = ParseFloat(f, f.D.FracValue);
                f.D0 = f.D1;
                f.D1 = ParseFloat(f, f.D.FracSlope);
                return SetState(f, next);
            case OP_SLP:
                f.D0 = f.D1;
                f.D1 = ParseFloat(f, f.D.FracSlope);
                return GetState(f);
            case OP_KEY:
                LaunchKeyData(f);
                f.P1 = ParseFloat(f, f.D.FracValue);
                f.Flags |= 0x40;
                return SetState(f, next);
            default:
                return 0;
        }
    }

    /// <summary>splGetHelmite, baselib/spline.c:9-28.</summary>
    public static float Hermite(float fterm, float time, float p0, float p1, float d0, float d1)
    {
        float _1_T2 = time * time;
        float t2 = fterm * fterm;
        float t2_T = _1_T2 * fterm;
        float t3_T2 = t2 * (_1_T2 * time);
        float _2t3_T3 = 2.0f * t3_T2 * fterm;
        float _3t2_T2 = 3.0f * _1_T2 * t2;
        return (d1 * (t3_T2 - t2_T)) + ((d0 * (time + ((t3_T2 - t2_T) - t2_T))) +
                                        ((p0 * (1.0f + (_2t3_T3 - _3t2_T2))) +
                                         (p1 * (-_2t3_T3 + _3t2_T2))));
    }

    static void UpdateAnim(St f, List<float> outv)
    {
        float v;
        switch (f.OpIntrp)
        {
            case OP_KEY:
                if ((f.Flags & 0x80) != 0) { v = f.P0; f.Flags = (byte)(f.Flags & 0x7F); }
                else return;
                break;
            case OP_CON:
                v = f.Time >= f.Fterm ? f.P1 : f.P0;
                break;
            case OP_LIN:
                if ((f.Flags & 0x20) != 0)
                {
                    f.Flags = (byte)(f.Flags & 0xDF);
                    if (f.Fterm != 0) f.D0 = (f.P1 - f.P0) / f.Fterm;
                    else { f.D0 = 0; f.P0 = f.P1; }
                }
                v = f.D0 * f.Time + f.P0;
                break;
            case OP_SPL0:
            case OP_SPL:
            case OP_SLP:
                if (f.Fterm != 0) v = Hermite((float)(1.0 / f.Fterm), f.Time, f.P0, f.P1, f.D0, f.D1);
                else v = f.P1;
                break;
            default:
                // OP_NONE: obj_update is still called with an uninitialised value in the
                // original. Never observed in fighter figatrees; treated as "no write".
                return;
        }
        outv.Add(v);
    }

    static void Interpret(St f, float rate, List<float> outv)
    {
        float fterm = 0.0f;
        uint state = GetState(f);
        if (state == 0) return;
        f.Time += rate;
        if (f.Time < 0.0f) return;
        for (; ; )
        {
            switch (state)
            {
                case 6:
                    f.Time += fterm;
                    LaunchKeyData(f);
                    UpdateAnim(f, outv);
                    return;
                case 1:
                case 2:
                    state = LoadData(f);
                    break;
                case 3:
                    if ((f.Flags & 0x80) != 0) UpdateAnim(f, outv);
                    state = LoadWait(f);
                    break;
                case 4:
                    if (f.Fterm <= f.Time)
                    {
                        state = 3;
                        fterm = f.Fterm;
                        f.Time -= f.Fterm;
                        SetState(f, state);
                        break;
                    }
                    UpdateAnim(f, outv);
                    SetState(f, 5);
                    return;
                case 5:
                    state = 4;
                    SetState(f, state);
                    break;
                default:
                    return;
            }
        }
    }

    /// <summary>
    /// Evaluates one track exactly as the tilt path does: HSD_FObjReqAnim(frame), then
    /// HSD_AObjInterpretAnim with AOBJ_FIRST_PLAY (rate 0), then HSD_AObjStopAnim (rate = framerate 1)
    /// if endFrame &lt;= frame. Returns the last value written to the joint (the object update callback
    /// may run several times; the final write wins), or null if nothing was written.
    /// </summary>
    public static float? Evaluate(FigaTrackData d, float frame, float endFrame)
    {
        var f = new St { D = d, Ad = 0, Time = (float)d.StartFrame + frame };
        SetState(f, 1);
        var outv = new List<float>(2);
        Interpret(f, 0.0f, outv);
        if (endFrame <= frame)
        {
            // HSD_FObjStopAnim -> FObj_FlushKeyData
            if (f.OpIntrp == OP_KEY) Interpret(f, 1.0f, outv);
            SetState(f, 0);
        }
        return outv.Count == 0 ? null : outv[^1];
    }
}
