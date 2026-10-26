function generate_campaign(job_path)
%GENERATE_CAMPAIGN Execute one isolated job without altering upstream equations.
% The Python launcher owns paths, checksums, campaign splits and acceptance gates.
job = jsondecode(fileread(job_path));
cd(job.simulator_directory);
assert(license('test', 'MATLAB') == 1, 'A MATLAB license is required.');
runtime.matlab_version = version;
runtime.release = version('-release');
runtime.computer = computer;
runtime.mex_extension = mexext;
for name = {'drying_model', 'deliquoring_grad_mex'}
    assert(exist(name{1}, 'file') == 3, 'Missing compatible MEX file: %s', name{1});
end
if strcmp(job.mode, 'preflight')
    write_json(job.metadata_file, runtime);
    return;
end

r = job.recipe;
u.t_cycle = r.t_cycle;
u.V_slurry = r.V_slurry;
u.P_compr = r.P_compr;
u.Tinlet_drying = r.Tinlet_drying;
cryst_output.conc_slurry = r.conc_slurry;
rng(job.seed, 'twister');
initial_rng_state = rng;
disturbance = job.scenario;
if isfield(job, 'disturbance_scale')
    % Only the explicit sweep patch accepts this scenario/size pair.
    disturbance = struct('scenario', job.scenario, 'scale', job.disturbance_scale);
end
simulation_output = run_simulation(u, cryst_output, disturbance, ...
    r.control_mode, r.total_duration, r.control_interval, ...
    r.sampling_interval, r.inter_cycle_Dt, r.mesh_clean_Dt);
assert(isstruct(simulation_output), 'Simulator returned no complete output.');
save(job.native_file, 'simulation_output', 'initial_rng_state', 'job', '-v7');

% Seventeen significant digits preserve doubles on a round-trip CSV read.
names = {'m_filt_WI101', 'P_PI101', 'P_PI102', 'c_slurry_AI101', ...
    'L_cake_LI101', 'V_slurry_LI101', 'Tg_in_TI101', 'Tg_out_TI102', 'Vdryer_FI101'};
measurements = simulation_output.measurements;
times = measurements.t_meas(:);
values = zeros(numel(times), numel(names) + 1);
values(:, 1) = times;
for index = 1:numel(names)
    channel = measurements.(names{index})(:);
    assert(numel(channel) == numel(times), 'Unequal channel length: %s', names{index});
    values(:, index + 1) = channel;
end
fid = fopen(job.sensor_file, 'w');
assert(fid >= 0, 'Cannot open sensor CSV.');
closer = onCleanup(@() fclose(fid));
fprintf(fid, '%s\n', strjoin([{'elapsed_seconds'}, names], ','));
fprintf(fid, [repmat('%.17g,', 1, numel(names)), '%.17g\n'], values');
clear closer;

runtime.rows = numel(times);
runtime.activation_seconds = [];
runtime.first_affected_sample = [];
if job.scenario ~= 0
    % Upstream disturbances() activates only at cycle starts strictly after 300s.
    boundaries = cumsum(simulation_output.operating_vars.t_cycle_vector);
    activation = boundaries(find(boundaries > 300, 1));
    assert(~isempty(activation), 'No disturbance activation in this recording.');
    runtime.activation_seconds = activation;
    runtime.first_affected_sample = find(times > activation, 1);
    assert(~isempty(runtime.first_affected_sample), 'No post-activation measurements.');
end
runtime.final_content = simulation_output.final_content;
runtime.total_production_kg = simulation_output.total_production;
write_json(job.metadata_file, runtime);
end

function write_json(path, value)
%WRITE_JSON Preserve runtime and quality metadata outside the sensor table.
fid = fopen(path, 'w');
assert(fid >= 0, 'Cannot open metadata JSON.');
closer = onCleanup(@() fclose(fid)); %#ok<NASGU>
fprintf(fid, '%s', jsonencode(value));
end
