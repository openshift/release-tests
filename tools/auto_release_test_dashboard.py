import json
import os

import pandas as pd
import streamlit as st
from github import Github, Auth

# Define the github access variables
repository_owner = 'openshift'
repository_name = 'release-tests'
directory_path = '_releases'
branch_name = 'record'

# Read the GitHub token from a system environment variable
github_token = os.environ.get('GITHUB_TOKEN')
if not github_token:
    st.warning("Oops, ENV VAR GITHUB_TOKEN NOT FOUND")
    st.stop()


# Create a GitHub instance with the token
gh = Github(auth=Auth.Token(github_token))

# Get the repository object
repo = gh.get_repo(f'{repository_owner}/{repository_name}')


def get_col_state(file_content):
    """
    Get job state: Accepted, Rejected, Pending
    """
    if 'accepted' in file_content:
        if file_content['accepted']:
            accepted = 'Accepted'
        elif 'manual_promotion' in file_content:
            accepted = 'Accepted (Manually Promoted)'
        else:
            accepted = 'Rejected'
    else:
        accepted = 'Pending'

    return accepted


def get_col_test_summary(file_content):
    """
    Get test summary for single job
    S: success, 1 or 2 successful jobs (including 2 retried jobs)
    F: failure
    WIP: pending
    """
    job_summaries = []
    job_links = []
    job_result = file_content['result']
    for job in job_result:
        results = []
        first_job = job['firstJob']
        if 'jobURL' not in first_job:
            # it means the job is just triggered, skip this file
            continue
        results.append(first_job['jobState'])
        job_links.append(first_job['jobURL'])
        if 'retriedJobs' in job:
            for retried_job in job['retriedJobs']:
                if 'jobURL' not in retried_job:
                    continue
                results.append(retried_job['jobState'])
                job_links.append(retried_job['jobURL'])

        if 'pending' in results:
            job_summaries.append('P')
        else:
            if len(results) == 1 and results.count('success') == 1:
                job_summaries.append('S')
            elif len(results) == 3 and results.count('success') == 2:
                job_summaries.append('S')
            else:
                job_summaries.append('F')

    return job_summaries, job_links


@st.dialog("Prow Job Links")
def dialog_with_links(links: list[str]):
    for link in links:
        st.link_button(link.removeprefix(
            'https://qe-private-deck-ci.apps.ci.l2s4.p1.openshiftapps.com/view/gs/qe-private-deck/logs/'), url=link)


@st.cache_data(ttl='3h')
def load_test_results(release='4.12'):
    # Get the contents of the specified directory
    directory_contents = repo.get_contents(
        path=directory_path, ref=branch_name)
    table_data = []
    for file in directory_contents:
        if file.name.startswith('ocp-test-result') and release in file.name:
            try:
                file_content = json.loads(file.decoded_content.decode('utf-8'))
                job_summary, job_links = get_col_test_summary(file_content)
                table_data.append(
                    {'Build': file.html_url,
                     'State': get_col_state(file_content),
                     'Test Result Summary': job_summary,
                     "Prow Jobs": job_links
                     })
            except json.JSONDecodeError:
                # don't need to handle the parsing error
                pass

    return pd.DataFrame(table_data)


# start to write page elements
st.set_page_config(layout='wide')
st.markdown("<h2 style='text-align: center'>Auto Release Test Results</h2>",
            unsafe_allow_html=True)
cola, colb = st.columns(2, vertical_alignment='bottom')
# define a select box to choose minor release, don't load all the test results together
with cola:
    release = st.selectbox(
        'Choose minor release',
        ("4.12", "4.13", "4.14", "4.15", "4.16", "4.17", "4.18", "4.19", "4.20", "4.21")
    )
# clear cache manually if you want to get latest results
with colb:
    if st.button("Refresh"):
        st.cache_data.clear()
# load test results and create dataframe
df = load_test_results(release)
event = st.dataframe(
    df,
    column_config={
        "Build": st.column_config.LinkColumn(
            display_text=r"https://github\.com/openshift/release-tests/blob/record/_releases/ocp-test-result-(\d.*\d+)-",
        ),
        "Prow Jobs": None
    },
    hide_index=True,
    height=1000,
    use_container_width=True,
    selection_mode='single-row',
    on_select='rerun'
)

# select event handler
if row := event['selection']['rows']:
    links = df.iloc[row]['Prow Jobs'].values[0]
    dialog_with_links(links)
