#!/usr/bin/env python

import os
import re
import subprocess
import datetime
import glob
import shutil
import argparse
import xml.etree.ElementTree as ET

ROOT_PATH = '.'
PATH_TO_POM_FILE = os.path.join( ROOT_PATH, 'pom.xml' )

# The mastodon core artifacts.
ARTIFACTS = [
	'mastodon-collection', 
	'mastodon-graph', 
	'mastodon',
	'mastodon-tracking',
	'mastodon-ellipsoid-fitting',
	'mastodon-selection-creator',
	'mastodon-pasteur',
	'mastodon-tomancak',
	'mastodon-app']
# Things needed by Mastodon not currently in Fiji core.
EXTRAS = [
	'mobie-io',
	'humble-video-all',
	'humble-video-noarch' ]
# Path to where the repos are cloned on your computer.
REPO_RELATIVE_PATH = '..'

def run_command( cmd, where, debug=False ):
	if debug:
		print( '  Running %s on %s' % ( cmd, where ) )
	try:
		out = subprocess.check_output( cmd, cwd = where, shell = True, stderr = subprocess.STDOUT )
		return True, out.decode('ISO-8859-1')
	except subprocess.CalledProcessError as e:
		return False, e.output.decode('ISO-8859-1')

def get_artifact_version( artifact_name ):
	"""Reads the module version in the pom by looking at the dependencies
	section."""

	# For the version of the other ones, they are set as a dep.
	regex = ( u"\<" + artifact_name + "\.version\>(.+)\</" + artifact_name + "\.version\>")
	with open( PATH_TO_POM_FILE, 'r' ) as pom_file:
		matches = re.finditer(regex, pom_file.read(), re.MULTILINE)
		for matchNum, match in enumerate(matches, start=1):
			return match.group(1)
	return ""

def check_if_clean( artifact, skip_up_to_date, skip_unstaged ):
	print( 'Checking repo %s ' % artifact )
	path = os.path.join( ROOT_PATH, REPO_RELATIVE_PATH, artifact )
	path = os.path.realpath( path )
	ok, out = run_command( "git status -uno", path )
	if not ok:
		print('Could not get git status: %s' % out)
		return False

	# Get branch name.
	branch_match = re.search( u"^On branch (.+)$", out, re.MULTILINE )
	if branch_match is not None:
		print( '  Current branch: %s' % branch_match.group( 1 ) )
		# Check if we are up to date.
		up_to_date = re.search( u"Your branch is up to date with", out, re.MULTILINE )
	else:
		tag_match = re.search( u"^HEAD detached at (.+)$", out, re.MULTILINE )
		print( '  Current tag: %s' % tag_match.group( 1 ) )
		# Check if we are up to date.
		up_to_date = re.search( u"nothing to commit", out, re.MULTILINE )

	if not skip_up_to_date and not up_to_date:
		print( '  Repo not up to date with remote. Aborting. ' )
		return False
	# Check if there are unstaged commits.
	unstaged = re.search( u"Changes not staged for commit:", out, re.MULTILINE )
	if not skip_unstaged and unstaged:
		print( '  There are unstaged changes. Aborting. ' )
		return False

	print( '  All good.' )
	return True

def git_pull( artifact ):
	print( 'Pulling in repo %s' % artifact )
	path = os.path.join( ROOT_PATH, REPO_RELATIVE_PATH, artifact )
	path = os.path.realpath( path )
	ok, out = run_command( "git pull", path )
	return ok, out

def git_checkout_master( artifact ):
	path = os.path.join( ROOT_PATH, REPO_RELATIVE_PATH, artifact )
	path = os.path.realpath( path )
	ok, out = run_command( "git checkout master", path )
	if not ok:
		print('  Could not checkout master branch: %s' % out)
		return False
	return True

def git_checkout_version( artifact, version, do_install ):
	if version.endswith('SNAPSHOT'):
		print( 'Not checking out SNAPSHOT version %s of module %s' % ( version, artifact ) )	
		return True # That's ok.

	path = os.path.join( ROOT_PATH, REPO_RELATIVE_PATH, artifact )
	path = os.path.realpath( path )
	# Git pull tags.
	print('Getting tags from remote.')
	ok, out = run_command( "git pull --tags", path )
	# Now checkout the desired version.
	print( 'Checking out version %s of module %s' % ( version, artifact ) )
	ok, out = run_command( "git -c advice.detachedHead=false checkout %s-%s" % ( artifact, version ), path )
	if not ok:
		print('  Could not checkout specified version: %s' % out)
		return False
	if do_install:
		print('  Building artifact.' )
		ok, out = run_command( "mvn clean install", path )
		if not ok:
			print('  Could not build artifact: %s' % out)
			return False
	return True

def get_branch_name( artifact ):
	path = os.path.join( ROOT_PATH, REPO_RELATIVE_PATH, artifact )
	path = os.path.realpath( path )
	ok, out = run_command( "git status -uno", path )
	branch_match = re.search( u"^On branch (.+)$", out, re.MULTILINE )
	if branch_match is not None:
		return branch_match.group( 1 )
	else:
		tag_match = re.search( u"^HEAD detached at (.+)$", out, re.MULTILINE )
		return tag_match.group( 1 )

def install( default_location = True ):
	if not default_location:
		branch_name = get_branch_name( 'mastodon' )
		t = datetime.date.today()
		if branch_name.lower().startswith( 'mastodon' ):
			target_dir = './%s-%s-all' % ( branch_name, t )
		else:
			target_dir = './Mastodon-%s-%s-all' % ( branch_name, t )
		
		target_dir = os.path.realpath( target_dir )
		if not os.path.exists( target_dir ):
			os.mkdir( target_dir )
		print( 'Installing to %s' % target_dir )
		cmd = "mvn clean install -Dscijava.app.directory=%s" % os.path.abspath( target_dir )
	else:
		print( 'Installing to default SciJava location' )
		cmd = "mvn clean install"
	# We need to build in the mastodon-app repo.
	mastodon_app_path = os.path.join(REPO_RELATIVE_PATH, 'mastodon-app')
	ok, out = run_command( cmd, mastodon_app_path )
	if not ok:
		print( 'Problem during install: %s' % out )
		return False

	if not default_location:
		subcopy_mastodon_jar( target_dir )

def subcopy_mastodon_jar( target_dir ):
	# Make a separate copy of just the mastodon jar if we have to.
	copy_dir = target_dir[0:-4]
	if not os.path.exists( copy_dir ):
		os.mkdir( copy_dir )

	
	jars_dir = os.path.join( ROOT_PATH, target_dir, 'jars' )
	print('Copying mastodon artifacts from %s to %s' % (jars_dir, target_dir) )
	for file in glob.glob(  os.path.join(jars_dir, 'mastodon-*.jar') ):
		print( '  Copying %s to %s ' % ( os.path.basename(os.path.normpath(file)), copy_dir ) )
		shutil.copy( file, copy_dir )
	print('Copying extra artifacts from %s to %s' % (jars_dir, target_dir) )
	for extra in EXTRAS:
		for file in glob.glob(  os.path.join(jars_dir, '%s-*.jar' % extra) ):
			print( '  Copying %s to %s ' % ( os.path.basename(os.path.normpath(file)), copy_dir ) )
			shutil.copy( file, copy_dir )

#-----------------------
# MAIN
#-----------------------

def run(install_to_default, is_preview, do_install, skip_up_to_date, skip_unstaged):

	if not is_preview:
		# Read the desired version.
		print( '\n----------------' )
		print( 'Version specified for artifacts:' )
		for artifact in ARTIFACTS:
			version = get_artifact_version( artifact )
			print( ' %30s -> %s' % ( artifact, version ) )

		# Check each module.
		print( '\n----------------' )
		print( 'Checking repos for cleanliness' )
		for artifact in ARTIFACTS:
			if not check_if_clean( artifact, skip_up_to_date, skip_unstaged ):
				return

		# Pull each module.
		print( '\n-------------------' )
		print( 'Checking out the specified versions:' )
		for artifact in ARTIFACTS:
			# git_pull( artifact )
			version = get_artifact_version( artifact )
			if not git_checkout_version( artifact, version, do_install ):
				return
		print( 'Done.' )

	print( '\n----------' )
	print( 'Installing' )
	install( install_to_default )
	print( 'Done.' )

	if not is_preview:

		# Go back to master.
		print( '\n----------' )
		print( 'Switching back to master branches' )
		for artifact in ARTIFACTS:
			ok = git_checkout_master( artifact )
			if ok:
				print( ' %30s -> %s' % ( artifact, 'done.' ) )

	print( 'Install finished. ')

if __name__ == "__main__":

	parser = argparse.ArgumentParser(description='Performs the compilation and deployment of the Mastodon artifacts.')
	parser.add_argument('--install-to-default', 
		action='store_true', 
		default=False, 
		help='If set, will install to the default SciJava location. Otherwise, will make a local directory with the jars.')
	parser.add_argument('--preview', 
		action='store_true', 
		default=False,
		help='If set, will run an installation from what is currently on disk. Otherwise we read the desired version from the pom and fetch them from remote.')
	parser.add_argument('--build', 
		action='store_true', 
		default=False,
		help='If set, will build (by running maven install) each artifact after checking out the version. This is desirable if the versions tagged have not been built yet.')
	parser.add_argument('--skip-up-to-date', 
		action='store_true', 
		default=False,
		help='If set, will not stop if the local repo is not in sync with the remote.')
	parser.add_argument('--skip-unstaged', 
		action='store_true', 
		default=False,
		help='If set, will not stop if the local repo has uncommitted changes.')
	
	args = parser.parse_args()

	install_to_default = args.install_to_default
	is_preview = args.preview
	do_install = args.build
	skip_up_to_date = args.skip_up_to_date
	skip_unstaged = args.skip_unstaged

	run(install_to_default, is_preview, do_install, skip_up_to_date, skip_unstaged)
