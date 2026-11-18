CREATE TABLE cad_projects (
    id varchar(36) PRIMARY KEY,
    owner_id varchar(36) REFERENCES users(id),
    name varchar(100) NOT NULL,
    head integer NOT NULL,
    created_at timestamptz NOT NULL
);
CREATE INDEX ix_cad_projects_owner_id ON cad_projects(owner_id);
CREATE TABLE cad_project_versions (
    project_id varchar(36) NOT NULL REFERENCES cad_projects(id),
    number integer NOT NULL,
    action_id varchar(36) NOT NULL,
    operation json NOT NULL,
    document json NOT NULL,
    order_id varchar(36) NOT NULL,
    job_id varchar(36) NOT NULL,
    created_at timestamptz NOT NULL,
    PRIMARY KEY (project_id, number),
    UNIQUE (project_id, action_id)
);
CREATE INDEX ix_cad_project_versions_job_id ON cad_project_versions(job_id);
