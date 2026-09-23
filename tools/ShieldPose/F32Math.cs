// Single-precision ports of the HSD / Dolphin SDK math used by the pose path.
// Every routine keeps the operation order of the decomp source it cites so that
// float32 rounding matches as closely as possible without emulating Gekko
// paired-single hardware. Deviations are listed in README.md.
namespace ShieldPose;

public struct Vec3f
{
    public float X, Y, Z;
    public Vec3f(float x, float y, float z) { X = x; Y = y; Z = z; }
}

public struct Quatf
{
    public float X, Y, Z, W;
    public Quatf(float x, float y, float z, float w) { X = x; Y = y; Z = z; W = w; }
}

/// <summary>3x4 row-major affine matrix, same layout as Dolphin `Mtx` (m[row][col], col 3 = translation).</summary>
public sealed class Mtx
{
    public readonly float[] M = new float[12];
    public float this[int r, int c] { get => M[r * 4 + c]; set => M[r * 4 + c] = value; }

    public static Mtx Identity()
    {
        var m = new Mtx();
        m[0, 0] = 1; m[1, 1] = 1; m[2, 2] = 1;
        return m;
    }

    public Mtx Clone()
    {
        var m = new Mtx();
        Array.Copy(M, m.M, 12);
        return m;
    }
}

public static class F32
{
    public const float Pi = 3.14159265358979323846f;

    // ---------------------------------------------------------------- quatlib.c

    /// <summary>EulerToQuat, baselib/quatlib.c:120-146 (ZYX convention).</summary>
    public static Quatf EulerToQuat(float ex, float ey, float ez)
    {
        float cx = MathF.Cos(0.5f * ex);
        float cy = MathF.Cos(0.5f * ey);
        float cz = MathF.Cos(0.5f * ez);
        float sx = MathF.Sin(0.5f * ex);
        float sy = MathF.Sin(0.5f * ey);
        float sz = MathF.Sin(0.5f * ez);
        float ss = sy * sz;
        float cc = cy * cz;
        Quatf q;
        q.W = cx * cc + sx * ss;
        q.X = sx * cc - cx * ss;
        q.Y = cz * (cx * sy) + sz * (sx * cy);
        q.Z = sz * (cx * cy) - cz * (sx * sy);
        return q;
    }

    /// <summary>HSD_QuatLib_8037EF28(p, q, out, t), baselib/quatlib.c:148-199. t=0 -> p, t=1 -> q.</summary>
    public static Quatf Slerp(Quatf p, Quatf q, float t)
    {
        float cosom = p.X * q.X + p.Y * q.Y + p.Z * q.Z + p.W * q.W;
        float sp, sq;
        Quatf o;
        if ((1.0f + cosom) > 1e-10f)
        {
            if ((1.0f - cosom) > 1e-10f)
            {
                float theta = MathF.Acos(cosom);
                float sinom = MathF.Sin(theta);
                sp = MathF.Sin((1.0f - t) * theta) / sinom;
                sq = MathF.Sin(t * theta) / sinom;
            }
            else
            {
                sq = t;
                sp = (float)(1.0 - (double)t);
            }
            o.X = sp * p.X + sq * q.X;
            o.Y = sp * p.Y + sq * q.Y;
            o.Z = sp * p.Z + sq * q.Z;
            o.W = sp * p.W + sq * q.W;
        }
        else
        {
            // Antipodal branch. The first assignment to `out` in the source is dead
            // (it is overwritten below), reproduced for completeness.
            if (t < 0.5f)
            {
                sp = MathF.Sin((float)(Math.PI / 2 * (1.0f - (2.0f * t))));
                sq = MathF.Sin((float)(Math.PI / 2 * (2.0f * t)));
            }
            else
            {
                t -= 0.5f;
                float t2 = 2.0f * t;
                sp = MathF.Sin((float)(Math.PI / 2 * (1.0f - t2)));
                sq = MathF.Sin((float)(Math.PI / 2 * t2));
            }
            o.X = sp * p.X + sq * q.X;
            o.Y = sp * p.Y + sq * q.Y;
            o.Z = sp * p.Z + sq * q.Z;
            o.W = sp * p.W + sq * q.W;
        }
        return o;
    }

    // ---------------------------------------------------------------- mtx.c (HSD)

    /// <summary>HSD_MtxSRT(m, scale, rot, trans, parentScl), baselib/mtx.c:362-410.</summary>
    public static Mtx MtxSRT(Vec3f s, Vec3f r, Vec3f t, Vec3f? pscl)
    {
        float sinX = MathF.Sin(r.X), cosX = MathF.Cos(r.X);
        float sinY = MathF.Sin(r.Y), cosY = MathF.Cos(r.Y);
        float sinZ = MathF.Sin(r.Z), cosZ = MathF.Cos(r.Z);

        float x2 = s.X, x1 = s.X, x0 = s.X;
        float y2 = s.Y, y1 = s.Y, y0 = s.Y;
        float z2 = s.Z, z1 = s.Z, z0 = s.Z;

        if (pscl is Vec3f p)
        {
            float t1 = (float)(1.0 / p.X);
            float t2 = (float)(1.0 / p.Y);
            float t3 = (float)(1.0 / p.Z);
            y2 *= p.Y * t1;
            z2 *= p.Z * t1;
            x1 *= p.X * t2;
            z1 *= p.Z * t2;
            x0 *= p.X * t3;
            y0 *= p.Y * t3;
        }

        var m = new Mtx();
        m[0, 0] = cosZ * (x2 * cosY);
        m[1, 0] = sinZ * (x1 * cosY);
        m[2, 0] = -x0 * sinY;
        m[0, 1] = y2 * ((cosZ * (sinX * sinY)) - (cosX * sinZ));
        m[1, 1] = y1 * ((sinZ * (sinX * sinY)) + (cosX * cosZ));
        m[2, 1] = cosY * (y0 * sinX);
        m[0, 2] = z2 * ((cosZ * (cosX * sinY)) + (sinX * sinZ));
        m[1, 2] = z1 * ((sinZ * (cosX * sinY)) - (sinX * cosZ));
        m[2, 2] = cosY * (z0 * cosX);
        m[0, 3] = t.X;
        m[1, 3] = t.Y;
        m[2, 3] = t.Z;
        return m;
    }

    /// <summary>HSD_MtxSRTQuat, baselib/mtx.c:412-434.</summary>
    public static Mtx MtxSRTQuat(Vec3f s, Quatf q, Vec3f t, Vec3f? pscl)
    {
        Mtx m = Scale(s.X, s.Y, s.Z);
        if (pscl is Vec3f p)
            m = Concat(Scale(p.X, p.Y, p.Z), m);
        m = Concat(QuatMtx(q), m);
        if (pscl is Vec3f p2)
            m = Concat(Scale((float)(1.0 / p2.X), (float)(1.0 / p2.Y), (float)(1.0 / p2.Z)), m);
        m = Concat(Trans(t.X, t.Y, t.Z), m);
        return m;
    }

    // ---------------------------------------------------------------- Dolphin SDK mtx.c

    public static Mtx Scale(float x, float y, float z)
    {
        var m = new Mtx();
        m[0, 0] = x; m[1, 1] = y; m[2, 2] = z;
        return m;
    }

    public static Mtx Trans(float x, float y, float z)
    {
        var m = Mtx.Identity();
        m[0, 3] = x; m[1, 3] = y; m[2, 3] = z;
        return m;
    }

    /// <summary>C_MTXQuat (libs/dolphin/src/dolphin/mtx/mtx.c:852-890). The game links PSMTXQuat, which
    /// computes 2/|q|^2 with fres + one Newton step; see README.</summary>
    public static Mtx QuatMtx(Quatf q)
    {
        float s = 2 / ((q.W * q.W) + ((q.Z * q.Z) + ((q.X * q.X) + (q.Y * q.Y))));
        float xs = q.X * s, ys = q.Y * s, zs = q.Z * s;
        float wx = q.W * xs, wy = q.W * ys, wz = q.W * zs;
        float xx = q.X * xs, xy = q.X * ys, xz = q.X * zs;
        float yy = q.Y * ys, yz = q.Y * zs, zz = q.Z * zs;
        var m = new Mtx();
        m[0, 0] = 1 - (yy + zz); m[0, 1] = xy - wz; m[0, 2] = xz + wy; m[0, 3] = 0;
        m[1, 0] = xy + wz; m[1, 1] = 1 - (xx + zz); m[1, 2] = yz - wx; m[1, 3] = 0;
        m[2, 0] = xz - wy; m[2, 1] = yz + wx; m[2, 2] = 1 - (xx + yy); m[2, 3] = 0;
        return m;
    }

    /// <summary>PSMTXConcat(a, b) = a*b. Mirrors the paired-single sequence (mul, madd, madd[, madd 1*t])
    /// with fused multiply-adds; Gekko's 25-bit frC rounding in ps_madd is not emulated.</summary>
    public static Mtx Concat(Mtx a, Mtx b)
    {
        var o = new Mtx();
        for (int i = 0; i < 3; i++)
        {
            float a0 = a[i, 0], a1 = a[i, 1], a2 = a[i, 2], a3 = a[i, 3];
            for (int j = 0; j < 4; j++)
            {
                float v = b[0, j] * a0;
                v = MathF.FusedMultiplyAdd(b[1, j], a1, v);
                v = MathF.FusedMultiplyAdd(b[2, j], a2, v);
                if (j == 3) v = MathF.FusedMultiplyAdd(1.0f, a3, v);
                o[i, j] = v;
            }
        }
        return o;
    }

    /// <summary>MTXMultVec(m, v): m * (v,1).</summary>
    public static Vec3f MultVec(Mtx m, Vec3f v)
    {
        Vec3f o;
        o.X = m[0, 0] * v.X + m[0, 1] * v.Y + m[0, 2] * v.Z + m[0, 3];
        o.Y = m[1, 0] * v.X + m[1, 1] * v.Y + m[1, 2] * v.Z + m[1, 3];
        o.Z = m[2, 0] * v.X + m[2, 1] * v.Y + m[2, 2] * v.Z + m[2, 3];
        return o;
    }

    /// <summary>Determinant of the 3x3 linear part, evaluated in double (diagnostic only).</summary>
    public static double Det3(Mtx m)
    {
        double a = m[0, 0], b = m[0, 1], c = m[0, 2];
        double d = m[1, 0], e = m[1, 1], f = m[1, 2];
        double g = m[2, 0], h = m[2, 1], i = m[2, 2];
        return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g);
    }

    /// <summary>Column norms of the 3x3 linear part, in double (diagnostic only).</summary>
    public static (double, double, double) ColNorms(Mtx m)
    {
        double n(int c) => Math.Sqrt((double)m[0, c] * m[0, c] + (double)m[1, c] * m[1, c] + (double)m[2, c] * m[2, c]);
        return (n(0), n(1), n(2));
    }

    /// <summary>Singular values (descending) of the 3x3 linear part, in double (diagnostic only).
    /// Eigenvalues of L^T L via the closed-form symmetric 3x3 solution.</summary>
    public static (double Max, double Mid, double Min) SingularValues(Mtx m)
    {
        var a = new double[3, 3];
        for (int i = 0; i < 3; i++)
            for (int j = 0; j < 3; j++)
            {
                double s = 0;
                for (int k = 0; k < 3; k++) s += (double)m[k, i] * m[k, j];
                a[i, j] = s;
            }
        double p1 = a[0, 1] * a[0, 1] + a[0, 2] * a[0, 2] + a[1, 2] * a[1, 2];
        double e1, e2, e3;
        if (p1 < 1e-30)
        {
            var d = new[] { a[0, 0], a[1, 1], a[2, 2] }.OrderByDescending(x => x).ToArray();
            e1 = d[0]; e2 = d[1]; e3 = d[2];
        }
        else
        {
            double q = (a[0, 0] + a[1, 1] + a[2, 2]) / 3;
            double p2 = Math.Pow(a[0, 0] - q, 2) + Math.Pow(a[1, 1] - q, 2) + Math.Pow(a[2, 2] - q, 2) + 2 * p1;
            double p = Math.Sqrt(p2 / 6);
            var b = new double[3, 3];
            for (int i = 0; i < 3; i++)
                for (int j = 0; j < 3; j++)
                    b[i, j] = (a[i, j] - (i == j ? q : 0)) / p;
            double detb = b[0, 0] * (b[1, 1] * b[2, 2] - b[1, 2] * b[2, 1])
                        - b[0, 1] * (b[1, 0] * b[2, 2] - b[1, 2] * b[2, 0])
                        + b[0, 2] * (b[1, 0] * b[2, 1] - b[1, 1] * b[2, 0]);
            double r = Math.Clamp(detb / 2, -1, 1);
            double phi = Math.Acos(r) / 3;
            e1 = q + 2 * p * Math.Cos(phi);
            e3 = q + 2 * p * Math.Cos(phi + 2 * Math.PI / 3);
            e2 = 3 * q - e1 - e3;
        }
        return (Math.Sqrt(Math.Max(e1, 0)), Math.Sqrt(Math.Max(e2, 0)), Math.Sqrt(Math.Max(e3, 0)));
    }

    // ---------------------------------------------------------------- lb_00CE.c

    /// <summary>lb_8000D008(y, x): custom atan2, lb/lb_00CE.c:106-151.</summary>
    public static float LbAtan2(float y, float x)
    {
        if (x < 0.00001f && x > -0.00001f)
        {
            if (y < 0.00001f && y > -0.00001f) return 0.0f;
            int s = y < 0.0f ? -1 : 1;
            return (float)((Math.PI / 2) * (double)s);
        }
        if (x > 0.0f) return MathF.Atan(y / x);
        // x < 0
        float r = y / x;
        if (r < 0.0f) r = -r;
        int sg = y < 0.0f ? -1 : 1;
        return (float)((double)sg * (Math.PI - MathF.Atan(r)));
    }
}
