using System.Globalization;
using System.Security.Claims;
using System.Security.Cryptography;
using System.Text;
using System.Text.Json.Nodes;
using Npgsql;

namespace Masar.Api;

public sealed class ApiError(int status, string code, string message) : Exception(message)
{
    public int Status { get; } = status;
    public string Code { get; } = code;
    public static ApiError Invalid(string message = "الطلب غير صالح.") => new(400, "invalid_request", message);
    public static ApiError Missing() => new(404, "not_found", "المورد غير موجود.");
    public static ApiError Conflict(string code = "version_conflict") => new(409, code, "تغيرت البيانات؛ حدّثها ثم حاول مرة أخرى.");
}

public sealed class Db(NpgsqlDataSource source)
{
    public ValueTask<NpgsqlConnection> Open(CancellationToken ct = default) => source.OpenConnectionAsync(ct);

    public static NpgsqlCommand Command(NpgsqlConnection connection, NpgsqlTransaction? transaction,
        string sql, params (string Name, object? Value)[] args)
    {
        var cmd = new NpgsqlCommand(sql, connection, transaction);
        foreach (var (name, value) in args)
            cmd.Parameters.AddWithValue(name, value ?? DBNull.Value);
        return cmd;
    }

    public static async Task<int> Execute(NpgsqlConnection connection, NpgsqlTransaction? transaction,
        string sql, CancellationToken ct = default, params (string Name, object? Value)[] args)
    {
        await using var cmd = Command(connection, transaction, sql, args);
        return await cmd.ExecuteNonQueryAsync(ct);
    }

    public static async Task<T?> Scalar<T>(NpgsqlConnection connection, NpgsqlTransaction? transaction,
        string sql, CancellationToken ct = default, params (string Name, object? Value)[] args)
    {
        await using var cmd = Command(connection, transaction, sql, args);
        var value = await cmd.ExecuteScalarAsync(ct);
        return value is null or DBNull ? default : (T)Convert.ChangeType(value, typeof(T), CultureInfo.InvariantCulture);
    }

    public static async Task<List<T>> Query<T>(NpgsqlConnection connection, NpgsqlTransaction? transaction,
        string sql, Func<NpgsqlDataReader, T> map, CancellationToken ct = default,
        params (string Name, object? Value)[] args)
    {
        await using var cmd = Command(connection, transaction, sql, args);
        await using var reader = await cmd.ExecuteReaderAsync(ct);
        var result = new List<T>();
        while (await reader.ReadAsync(ct)) result.Add(map(reader));
        return result;
    }

    public static Task<int> Audit(NpgsqlConnection conn, NpgsqlTransaction? tx, Guid? actor,
        string action, string resource, JsonObject? details = null, CancellationToken ct = default) =>
        Execute(conn, tx, "INSERT INTO public.audit(actor_id,action,resource_id,details) VALUES (@actor::uuid,@action,@resource,@details::jsonb)",
            ct, ("actor", actor), ("action", action), ("resource", resource), ("details", (details ?? new JsonObject()).ToJsonString()));
}

public static class Input
{
    public static string Text(string? value, int min, int max, bool trim = true)
    {
        if (value is null) throw ApiError.Invalid();
        var text = trim ? value.Trim() : value;
        if (text.Length < min || text.Length > max || text.Contains('\0')) throw ApiError.Invalid();
        return text;
    }

    public static string UserName(string? value)
    {
        var name = Text(value, 3, 160).Normalize(NormalizationForm.FormKC).ToLowerInvariant();
        if (name.Length is < 3 or > 40 || !name.EnumerateRunes().All(r => Rune.IsLetterOrDigit(r) || r.Value is '.' or '_' or '-'))
            throw ApiError.Invalid("اسم المستخدم يجب أن يكون من 3 إلى 40 حرفًا أو رقمًا، مع . أو _ أو - فقط.");
        return name;
    }

    public static string Hash(string value) => Convert.ToHexStringLower(SHA256.HashData(Encoding.UTF8.GetBytes(value)));
    public static Guid UserId(HttpContext context) => Guid.Parse(context.User.FindFirstValue(ClaimTypes.NameIdentifier)!);
    public static string String(JsonNode? value) => value?.GetValue<string>() ?? "";
    public static string Id(string? value) => Text(value, 1, 100);
}
