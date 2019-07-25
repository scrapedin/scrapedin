#!/usr/bin/python3
import sys
import argparse
import re
import csv
import os
import getpass
import logging
import time

try:
	from tabulate import tabulate
except ImportError:
	print('Missing required package: Tabulate')
	sys.exit(os.EX_SOFTWARE)

try:
	from selenium.webdriver.common.by import By
	from selenium.webdriver.support.ui import WebDriverWait
	from selenium.webdriver.support import expected_conditions as EC
	from selenium import webdriver
	from selenium.common import exceptions

except ImportError:
	print('Missing required package: selenium\n')
	print('Did you forget to run setup.py?\npython3 setup.py install')
	sys.exit(os.EX_SOFTWARE)

HELP_EPILOG = """
You may specify multiple formats by using a comma. Using {domain} will
dynamically pick the domain based off of the company name. Here are some common
formats:

Format                       Schema
---------------------------  -----------------------------
[First Initial] [Last Name]  {first:.1}{last}@{domain}.com
[First Name] [Last Initial]  {first}{last:.1}@{domain}.com
[First Name].[Last Name]     {first}.{last}@{domain}.com
[Last Name].[First Name]     {last}.{first}@{domain}.com
"""


class Webpage:
	def __init__(self, loglvl='INFO'):
		capabilities = webdriver.DesiredCapabilities().FIREFOX
		capabilities["marionette"] = True
		self.page = webdriver.Firefox(log_path='/dev/null', capabilities=capabilities)
		self.employee_data = {}
		self.log = logging.getLogger(
			logging.basicConfig(level=getattr(logging, loglvl), format="%(name)-15s %(levelname)-10s %(asctime)-10s %(message)s")
		)

	def enter_data(self, field, text):
		'''
		Enter data by providing the Id of the HTML field and the text you would like to enter.

		web = Webpage()
		web.enter_data('your_field', 'the data you want entered')

		:param str field: HTML field to enter data
		:param str text: The text you want entered into "field"
		:rtype: None
		'''
		self.page.execute_script("document.getElementById(\"" + field + "\").setAttribute('value', \"" + text + "\")")

	@staticmethod
	def sanitize_name(name):
		'''
		Takes a given name and sanitizes it for use as an email address.  If a name contains more than 4 words
		or non ASCII characters other than , or ( and ) then it will NOT be used.

		If a name contains a , then we can safely split on that character and reliably detect the users name.

		Names like: John (Allan) Doe are normally put in place for people who go by a nickname.  The script will break
		these names into two separate names:
			- John Doe
			- Allan Doe

		:param str name: Persons name
		:rtype: str or None
		'''
		if ',' in name:
			name = name.split(',')[0]

		if len(name.split()) > 4:
			# Too many words in the name..Won't be able to reliably create an email address.
			return None

		if re.search("[(].*[)]", name):
			name_list = []
			# Sometimes nicknames are put in parenthesis.  This will find those and create two email guesses.
			# First Last
			# text_in_parenthesis Last
			nickname = re.search("[(].*[)]", name).group()
			true_name = ' '.join([i.strip() for i in name.split(nickname)])
			if re.match("^[' a-zA-Z']*$", true_name):
				name_list.append(true_name)

			fixed_nickname = nickname.replace('(', '').replace(')', '').strip()

			nick = [i.strip() for i in name.replace(nickname, '').split()]
			nick[0] = fixed_nickname
			nick = ' '.join(nick)
			if re.match("^[' a-zA-Z']*$", nick):
				name_list.append(nick)

			return name_list

		elif re.match("^[' a-zA-Z']*$", name):
			# Only matches if the name contains uppercase, lowercase or spaces.
			return [name]

		else:
			return None

	def login(self, username, password):
		'''
		Login to the linked in web page.

		The only args required to use this function are the username and password to log into linkedin.

		Example usage:
			parser = argparse.ArgumentParser()
			required = parser.add_argument_group('required arguments')
			required.add_argument('-u', dest='username', required=True, help='LinkedIn Login Email')
			args = parser.parse_args()

			password = getpass.getpass(prompt='LinkedIn Password: ')

			web = WebPage()
			web.login(username, password)

		:param argparse username: argparse object with the attribute "username"
		:param argparse password:
		:rtype: None
		'''
		self.page.get("https://www.linkedin.com/login?trk=guest_homepage-basic_nav-header-signin")

		WebDriverWait(self.page, 10).until(EC.presence_of_element_located((By.NAME, 'session_key')))
		self.enter_data('username', username)
		self.enter_data('password', password)

		# Submit login button
		try:
			self.page.execute_script("arguments[0].click();", self.page.find_element_by_class_name("btn__primary--large"))
			WebDriverWait(self.page, 20).until(EC.visibility_of_element_located((By.CLASS_NAME, 'extended-nav')))
		except exceptions.TimeoutException:
			# Sometimes the javascript fails to execute. This means "sign in" will not be pressed.
			self.page.execute_script("arguments[0].click();", self.page.find_element_by_class_name("btn__primary--large"))

	def apply_filters(self, company, url=None, georegion=None, industry=None, job_title=None):
		'''
		Utilize the method within the cycle_users function to build different search
		parameters such as location, geotag, company, job-title, etc.
		This function will return the full URL.

		:param str company: target company name
		:param str url: default (or custom) linkedin url for faceted linkedin search
		:param str georegion: geographic region (-g) to filter
		:param str industry: industry (-i_ to filter
		:param str job_title: job title (-j) to filter
		:rtype: string (url if successful) or int (Unix-style error integer if error is encountered)
		'''
		filters = []
		if not url:
			url = 'https://www.linkedin.com/search/results/people/?'

		# Filter by Company
		# Allows the user to scrape linkedin without specifying a target company, but must do so with intent
		if company != "NONE":
			filters.append('company={0}'.format(company))

		#Filter by Geographic Region
		if georegion:
			# region object is created for future-proof purposes in the event new filters become available or formating changes
			region = {}
			try:
				region['full_line'] = list_search('georegion', term=georegion, return_results=True)
				region['name'] = region['full_line'].split('\t')[-1]
				region['code'] = region['full_line'].split('\t')[0].split('.') 	# Should be continent.country.province/state.city_id
				region.update({key: value.replace(' ', '') for (key, value) in zip(('continent', 'country', 'state', 'id'), region['code'])})
				filters.append('facetGeoRegion=%5B"{0}%3A{1}"%5D'.format(region['country'], region['id']))
			except (IndexError, KeyError, ValueError):
				self.log.error("[-] The region you chose is too broad to search. Search by City only")
				return os.EX_NOINPUT

		# Filter by Industry
		if industry:
			ind = list_search('industry', term=industry, return_results=True)
			if ind:
				i_code = ind.split('\t')[0].replace(' ', '')
				filters.append('facetIndustry=%5B"{0}"%5D'.format(i_code))
		filters.append("origin=FACETED_SEARCH")
		if job_title:
			filters.append('title={0}'.format(job_title))
		else:
			filters.append('title=')
		# Join additional parameters to the URL by ampersand (&). Order doesn't matter.
		url += "&".join(filters).lstrip("&") if len(filters) > 1 else filters[0]
		self.log.debug("Filtered URL: " + url)
		return url

	def cycle_users(self, company, url, max_users=None):
		'''
		You must run the login method before cycle_users will run.  Once the login method has run, cycle_users can
		collect the names and titles of employees at the company you specify.  This method requires the company name
		and optional value max_users from argparse.  See the login method for a code example.

		:param argparse company:
		:param argpase max_users:
		:rtype: None (self.employee_data will be populated with names, titles and profile URLs)
		'''
		# Wait for home screen after login
		WebDriverWait(self.page, 20).until(EC.visibility_of_element_located((By.CLASS_NAME, 'extended-nav')))
		self.log.debug("URL: " + str(url))
		self.page.get(url)
		count = 1  # WebElements cannot be used for iteration..
		current_page = 1

		if not max_users:
			max_users = float('inf')

		while max_users > len(self.employee_data) and current_page < 100:
			self.page.execute_script("window.scrollTo(0, document.body.scrollHeight);")
			try:
				WebDriverWait(self.page, 20).until(EC.visibility_of_element_located((By.CLASS_NAME, 'active')))
				# Check if the page contains the "no search results" class. This means we are out of users
				# This will raise a NoSuchElementException if the element is not found
				self.page.find_element_by_class_name("search-no-results__container")
				break
			except exceptions.NoSuchElementException:
				pass
			except exceptions.TimeoutException:
				# Page didn't load correctly after 20 seconds, cannot reliably recover. Bailing.
				return

			try:
				WebDriverWait(self.page, 5).until(EC.visibility_of_element_located((By.CLASS_NAME, 'name')))
			except exceptions.TimeoutException:
				try:
					if self.page.find_elements_by_class_name('actor-name'):
						# If this is true, the page is filled with "LinkedIn Member".  It doesn't mean there's no users
						# available on the page.  If this is the case, click next.
						current_page += 1
						if 'disabled=""' in self.page.find_element_by_class_name("artdeco-pagination__button--next").parent.page_source:
							# If this is true then the Next button is "disabled". This happens when there's no more pages
							break
						self.page.execute_script("arguments[0].click();", self.page.find_element_by_class_name("artdeco-pagination__button--next"))
						continue
				except exceptions.NoSuchElementException:
					# Reached when there's no more users available on the page.
					break

			try:
				# Get the current page number (at the bottom of a company search)
				# The value returned from the HTML looks like this: '1\nCurrent page'
				new_page = int(self.page.find_elements_by_class_name('active')[-1].text.split()[0])

			except ValueError:
				# If there's only one page, linkedin doesn't show page numbers at the bottom.  The only result
				# will be the text string "people", therefore when we try to convert the value to int we raise
				# an exception
				new_page = 1

			except IndexError:
				# Page likely came back with "No more users" even though there appeared to be pages left
				return

			except exceptions.StaleElementReferenceException:
				# Handles a race condition where elements are found but are not populated yet.
				continue

			for pagnation in self.page.find_elements_by_class_name("artdeco-pagination__button"):
				if pagnation.text != "Next":
					continue

				if not pagnation.is_enabled():
					# Next button is disabled.. This is linkedins way of saying "We are done here"
					return

			if current_page != new_page:
				# The script is too fast.  This verifies a new page has loaded before proceeding.
				continue

			# Scroll to the bottom of the page loads all elements (employee_names)
			self.page.execute_script("window.scrollTo(0, document.body.scrollHeight);")
			# Give the elements a second to populate fully
			time.sleep(1)
			employee_elements = self.page.find_elements_by_class_name('search-result__wrapper')

			for employee in employee_elements:
				if count > len(employee_elements):
					count = 1
					current_page += 1
					# click next page
					try:
						self.page.execute_script("arguments[0].click();", self.page.find_element_by_class_name("artdeco-pagination__button--next"))
						break
					except exceptions.NoSuchElementException:
						# No more pages
						return os.EX_OK

				try:
					name = Webpage.sanitize_name(employee.find_element_by_class_name('name').text)
					title_text = employee.find_element_by_class_name('subline-level-1').text

					try:
						# This line/element does not always exist, so an exception will always be raised in this case and must be handled.
						alt_text = employee.find_element_by_class_name('search-result__snippets').text
					except exceptions.NoSuchElementException:
						alt_text = False
					title, _, company = title_text.partition(' at ')
					if alt_text and not company:
						alt_text = alt_text.lstrip('Current: ')
						title, _, company = alt_text.partition(' at ')
					dept = self.dept_wizard(title)
					# If company is still empty at this point, bail out to unemployment
					company = company or 'UNEMPLOYED'
					region = employee.find_element_by_class_name("subline-level-2").text
					url = employee.find_element_by_css_selector('a').get_attribute('href')

				except (IndexError, exceptions.NoSuchElementException):
					count += 1
					continue

				if not name:
					continue
				for person in name:
					self.log.info(person)
					self.employee_data.update({person: [dept, title, company, region, url]})

					count += 1

	@staticmethod
	def dept_wizard(linkedin_title):
		'''
		Attempt to determine which department a given user belongs to based off of their title. If a title cannot
		be reliably determined then it will return a blank string. It is advised to compare their raw untouched
		titles to the output of dept_wizard(). Blindly trusting the dept_wizard() could lead to some awkward situations.

		If a title matches any of the values in the tuples below, the first value in the tuple will populate the title
		column in the CSV.

		:param str linkedin_title: a string reflecting an employees title
		:rtype: str
		'''

		sales = ('Sales', 'Account Manager', 'Account Executive', 'New Business', 'Relationship Manager')
		hr = ('HR', 'Human Resources', 'Benefits Admin', 'Payroll', 'Talent', 'Recruiter')
		accounting = ('Accounting', 'Accountant', 'Financial', 'Finance', 'Billing')
		marketing = ('Marketing', 'Content', 'Brand', 'seo', 'Social Media')
		it = ('IT', 'Information Technology', 'Network Engineer', 'Network Admin', 'System Admin', 'sysadmin', 'sys admin', 'Help Desk', 'ITHD', 'Developer', 'Dev')
		infosec = ('Infosec', 'Red Team', 'Blue Team', 'Offensive', 'Defensive', 'Pentest', 'Penetration', 'Information Security')
		executive = ('Executive', 'Exec', 'cfo', 'ceo', 'coo', 'cio', 'cmo', 'cbo', 'cto', 'cso', 'Chief')
		audit = ('Audit', 'Compliance')

		all_depts = [sales, hr, accounting, marketing, it, infosec, executive, audit]

		for dept in all_depts:
			for common_title in dept:
				if re.match('(^|\s)' + re.escape(common_title.lower()) + '($|\s)', linkedin_title.lower()):
					return dept[0]

	def out_csv(self, filename, company, schema):
		'''
		Write data from self.employee_data to a CSV.  This data is populated from the cycle_users method.

		:param argparse filename: argparse object with attribute "file"
		:rtype: None
		'''
		if not self.employee_data:
			return None
		csv_file = csv.writer(open(filename, "w"))

		for name, emp_data in self.employee_data.items():
			emails = self.email_formatter(name, company, schema)
			for email in emails:
				first_name = name.split()[0]
				last_name = name.split()[-1]
				data = [first_name, last_name, email] + emp_data
				csv_file.writerow(data)

	def email_formatter(self, name, company, schema):
		'''
		This method is called by out_csv to determine what format emails should be outputted into.  The char_map determines
		which indexes to use when generating a username in the __prepare_username__ method.

		:param str name:
		:param argparse format: argparse object with attribute "format"
		:param argparse company: argparse object with attribute "company"
		:rtype: list emails
		'''
		emails = []

		for selected in schema:
			names = name.split()
			email = selected.format(first=names[0], last=names[-1], domain=company.replace(' ', ''))
			emails.append(email)
		return emails

	@staticmethod
	def verify_schema(schema):
		'''
		Verify the chosen email schema is valid.

		:param str schema: A comma separated string containing one or more email schema formats
		:rtype: list of all valid schemas
		'''
		schema = schema.split(',')
		for email_format in schema:
			try:
				email_format.format(first='test', last='test', domain='test')
			except KeyError:
				raise SyntaxWarning('Invalid schema: ' + email_format)
		return schema

def list_search(target, term, return_results=False):
	'''
	Prints list of possible geographic regions & industries per LinkedIn Documentation
	Specify -l by itself to print all files, or specify -g <term> / -i <term> to search
	for matching geographic regions and industries simultaneously.

	Exact matches are required for faceted searches of georegions or industries.

	:param str target: Search for a matching georegion or industry by specifying -g or -i parameters
	:param str term: Search for specific matching term in -g or -i by adding a term argument to search for
	:return: List of matches
	'''
	print("========================= {0} =========================".format(target.capitalize()))
	try:
		refs = os.path.join(os.path.dirname(os.path.realpath(__file__)), 'refs/')
		if target == 'georegion':
			search_file = open(os.path.join(refs, 'georegions.txt'), 'r')
		elif target == 'industry':
			search_file = open(os.path.join(refs, 'industries.txt'), 'r')
		else:
			return os.EX_NOINPUT
	except IOError as unfound_file:
		print("[-] You are missing the {0}.txt file from your ./refs installation directory. Please re-install scrapedin.".format(target))
		print(unfound_file)
		return os.EX_IOERR

	results = []

	for i, line in enumerate(search_file.readlines()):
		if term.lower() in line.lower():
			results.append([str(line.split()[0]), str(' '.join(line.split()[1:])).strip('\n')])
			#print('[{0}] {1}'.format(i, line.strip('\n')))
	search_file.close()
	if return_results:
		print("Matches found: ", results)
		return results[0][0]
	print(tabulate(results, headers=['CODE', 'NAME'], tablefmt="orgtbl"))
	return os.EX_OK


def main():
	parser = argparse.ArgumentParser(epilog=HELP_EPILOG, formatter_class=argparse.RawTextHelpFormatter)
	parser.add_argument('-m', dest='max_users', type=int, default=float('inf'), help='The maximum amount of employees to scrape (default: all)')
	parser.add_argument('-l', dest='list_search', action='store_true', default=False, help='List search for geographic regions and industries. (requires -g or -l)')
	parser.add_argument('-L', dest='loglvl', action='store', choices=['DEBUG', 'INFO', 'WARNING', 'ERROR', 'CRITICAL'], default='INFO', help='set the logging level')
	parser.add_argument('-U', dest='url', action='store', default=None, help='Explicitly set the company URL to scrape from')

	parser.add_argument('-g', dest='georegion', action='store', default=None, help='Filter results by geographic region')
	parser.add_argument('-i', dest='industry', action='store', default=None, help='Filter results by industry')
	parser.add_argument('-j', dest='job_title', action='store', default=None, help='Filter results by job title')

	required = parser.add_argument_group('required arguments')
	required.add_argument('-c', dest='company', action='store', default=None, help='The company name to scrape users from LinkedIn. Enter "NONE" to scrape users without company')
	required.add_argument('-o', dest='filename', help='The output filename')
	required.add_argument('-u', dest='username', help='LinkedIn Login Email')
	required.add_argument('-s', dest='schema', default='{first:.1}{last}@{domain}.com', help='The email format to use')
	args = parser.parse_args()

	# If -l is true, search by term or print entire file. -o and -u are not required
	if args.list_search:
		if not args.georegion and not args.industry:
			list_search(target='georegion', term=' ')
			list_search(target='industry', term=' ')

		if args.georegion:
			list_search(target='georegion', term=args.georegion)
		if args.industry:
			list_search(target='industry', term=args.industry)

		return os.EX_OK

	# If -l is False (default), -o and -u are required
	if not args.filename or not args.username:
		parser.error('the following arguments are required to begin scraping -o, -u')
		return os.EX_NOINPUT

	if not args.company:
		parser.error('the following arguments are required to begin scraping -c\n\tNOTE: If you are trying to scrape users without a company target, use "-c NONE"')

	try:
		args.schema = Webpage.verify_schema(args.schema)
	except SyntaxWarning as invalid_schema:
		print(invalid_schema)
		sys.exit(os.EX_SOFTWARE)

	if not args.filename.endswith('.csv'):
		args.filename += '.csv'

	if args.company:
		if '"' in args.company:
			args.company = args.company.replace('"', '')

	web = None
	try:
		password = getpass.getpass(prompt='LinkedIn Password: ')
		web = Webpage(loglvl=args.loglvl)
		web.login(username=args.username, password=password)
		del password
		if not args.url:
			url = 'https://www.linkedin.com/search/results/people/?'
			if args.georegion or args.industry or args.job_title:
				filtered_url = web.apply_filters(args.company, url, args.georegion, args.industry, args.job_title)
				# Error handler for when apply_filters returns an ox.EX_ code
				if isinstance(filtered_url, (int)):
					return filtered_url
				# Filtered URL
				web.cycle_users(args.company, filtered_url, args.max_users)
			else: 	# Default URL
				url += "company={0}".format(args.company)
				web.cycle_users(args.company, url, args.max_users)
		else:	# User-defined URL
			web.cycle_users(args.company, args.url, args.max_users)
		web.out_csv(filename=args.filename, company=args.company, schema=args.schema)
		web.page.quit()

	except KeyboardInterrupt:
		if web:
			web.out_csv(args.filename, args.company, args.schema)
		return os.EX_OK

if __name__ == '__main__':
	if sys.version_info < (3, 3):
		print('[-] this script requires Python 3.3+')
		sys.exit(os.EX_SOFTWARE)
	sys.exit(main())
