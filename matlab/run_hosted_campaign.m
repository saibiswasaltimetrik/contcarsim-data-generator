function run_hosted_campaign(index_path)
%RUN_HOSTED_CAMPAIGN Run frozen jobs inside the officially licensed hosted action.
% Each job resets its own recorded RNG seed. Upstream equations remain untouched.
index_path = fullfile(pwd, index_path);
index = jsondecode(fileread(index_path));
started = tic;
completed = {};
diary(fullfile(index.results_directory, 'matlab.log'));
cleanup = onCleanup(@() diary('off')); %#ok<NASGU>
for number = 1:numel(index.jobs)
    fprintf('Recording %d of %d\n', number, numel(index.jobs));
    generate_campaign(index.jobs{number});
    completed{end + 1} = index.entries(number).run_id; %#ok<AGROW>
end
result.completed = completed;
result.elapsed_seconds = toc(started);
fid = fopen(fullfile(index.results_directory, 'completed.json'), 'w');
assert(fid >= 0, 'Cannot write campaign completion metadata.');
closer = onCleanup(@() fclose(fid)); %#ok<NASGU>
fprintf(fid, '%s', jsonencode(result));
end
