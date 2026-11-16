namespace Masar.Api;

internal sealed class CodeLabWorker(CodeLabQueue queue, CodeLabRunner runner, ILogger<CodeLabWorker> logger)
    : BackgroundService
{
    protected override Task ExecuteAsync(CancellationToken stoppingToken) => runner.Available
        ? Task.WhenAll(Enumerable.Range(0, CodeLabQueue.WorkerSlots).Select(_ => ProcessQueue(stoppingToken)))
        : Task.CompletedTask;

    private async Task ProcessQueue(CancellationToken ct)
    {
        while (!ct.IsCancellationRequested)
        {
            try
            {
                var job = await queue.Claim(ct);
                if (job is null)
                {
                    await Task.Delay(TimeSpan.FromMilliseconds(500), ct);
                    continue;
                }
                await queue.Finish(await Execute(job, ct), ct);
            }
            catch (OperationCanceledException) when (ct.IsCancellationRequested)
            {
                return;
            }
            catch (Exception ex) when (!ct.IsCancellationRequested)
            {
                logger.LogWarning("Code lab queue processing failed ({ExceptionType}).", ex.GetType().Name);
                await Task.Delay(TimeSpan.FromSeconds(3), ct);
            }
        }
    }

    private async Task<CodeLabRunResult> Execute(CodeLabJob job, CancellationToken ct)
    {
        if (job.TestCases.Length == 0)
        {
            var result = await runner.Execute(job.Language, job.Code, job.Stdin, ct);
            return new CodeLabRunResult(job.Id, result.Status, "not_evaluated",
                result.Stdout.Replace("\0", ""), result.Stderr.Replace("\0", ""), null, null, false);
        }

        var passed = 0;
        foreach (var test in job.TestCases)
        {
            var result = await runner.Execute(job.Language, job.Code, test.Input, ct);
            // Learner code can echo its input or leak it in an error. Assessment only publishes aggregate results.
            if (result.Status != "completed")
                return new CodeLabRunResult(job.Id, result.Status, "not_evaluated", "", "", null, null, false);
            if (string.Equals(NormalizeOutput(result.Stdout), NormalizeOutput(test.ExpectedOutput), StringComparison.Ordinal))
                passed++;
        }

        var verdict = passed == job.TestCases.Length ? "passed" : "needs_work";
        return new CodeLabRunResult(job.Id, "completed", verdict, "", "", passed, job.TestCases.Length, false);
    }

    private static string NormalizeOutput(string value)
    {
        var normalized = value.Replace("\r\n", "\n", StringComparison.Ordinal);
        return normalized.EndsWith('\n') ? normalized[..^1] : normalized;
    }
}
